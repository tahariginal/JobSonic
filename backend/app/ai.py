"""Optional AI layer. Off unless BOTH the environment switch and the dashboard switch are on.

Execution method `claude_cli` shells out to the locally installed Claude Code in headless
print mode, with every tool disabled and a per-call spend cap. It uses whatever account that
CLI is logged in with. It is never started for routine discovery: only for explicitly requested
or shortlisted work, and every call is budgeted, cached and logged.

Job descriptions are untrusted text: the model gets no tools and its output is parsed as data
and validated before anything is stored.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import tempfile
from datetime import timedelta
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import get_settings
from .core import get_setting
from .db import utcnow
from .models import AICache, AIUsage

log = logging.getLogger("sonic.ai")


class AIUnavailable(Exception):
    pass


def usage_summary(db: Session) -> dict:
    now = utcnow()
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month = day.replace(day=1)

    def agg(since):
        calls, cost, tin, tout = db.execute(
            select(func.count(AIUsage.id), func.coalesce(func.sum(AIUsage.est_cost_usd), 0),
                   func.coalesce(func.sum(AIUsage.input_tokens), 0), func.coalesce(func.sum(AIUsage.output_tokens), 0))
            .where(AIUsage.created_at >= since, AIUsage.cached.is_(False))
        ).one()
        return {"calls": calls, "est_cost_usd": round(float(cost), 4), "input_tokens": int(tin), "output_tokens": int(tout)}

    cached = db.scalar(select(func.count(AIUsage.id)).where(AIUsage.cached.is_(True))) or 0
    return {"today": agg(day), "month": agg(month), "all_time": agg(now - timedelta(days=36500)), "cache_hits": cached}


def status(db: Session) -> dict:
    cfg = get_setting(db, "ai")
    mode = get_settings().ai_mode
    use = usage_summary(db)
    reason = ""
    if mode == "off":
        reason = "AI execution is disabled on the server (SONIC_AI_MODE=off)."
    elif mode != "claude_cli":
        reason = f"Unknown AI mode “{mode}”."
    elif not cfg.get("enabled"):
        reason = "AI is switched off in Settings."
    elif use["today"]["calls"] >= cfg["daily_call_budget"]:
        reason = "Daily AI call budget reached."
    elif use["month"]["calls"] >= cfg["monthly_call_budget"]:
        reason = "Monthly AI call budget reached."
    elif use["today"]["est_cost_usd"] >= cfg["daily_usd_budget"]:
        reason = "Daily AI cost budget reached."
    elif use["month"]["est_cost_usd"] >= cfg["monthly_usd_budget"]:
        reason = "Monthly AI cost budget reached."
    return {"available": not reason, "reason": reason, "mode": mode, "model": get_settings().ai_model,
            "config": cfg, "usage": use}


def _extract_json(text: str) -> Optional[dict]:
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"):]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        out = json.loads(text[start: end + 1])
        return out if isinstance(out, dict) else None
    except json.JSONDecodeError:
        return None


def _run_claude_cli(prompt: str, system: str, timeout: int = 180) -> tuple[str, dict]:
    s = get_settings()
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_CODE", "CLAUDECODE", "ANTHROPIC_"))}
    # No ANTHROPIC_API_KEY is ever passed through: this path can only use the CLI's own login,
    # so it cannot silently fall back to metered API billing.
    cmd = [s.claude_bin, "-p", "--output-format", "json", "--model", s.ai_model, "--tools", "",
           "--strict-mcp-config", "--no-session-persistence", "--setting-sources", "",
           "--system-prompt", system]
    with tempfile.TemporaryDirectory(prefix="sonic-ai-") as cwd:
        proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout, cwd=cwd, env=env)
    if proc.returncode != 0:
        raise AIUnavailable(f"claude exited {proc.returncode}: {(proc.stderr or proc.stdout)[:300]}")
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise AIUnavailable(f"unparseable CLI output: {e}") from e
    if isinstance(data, list):  # some versions emit an event array
        data = next((d for d in reversed(data) if isinstance(d, dict) and d.get("type") == "result"), {})
    if data.get("is_error"):
        raise AIUnavailable(str(data.get("result"))[:300])
    usage = data.get("usage") or {}
    meta = {
        "input_tokens": int(usage.get("input_tokens", 0)) + int(usage.get("cache_read_input_tokens", 0)) + int(usage.get("cache_creation_input_tokens", 0)),
        "output_tokens": int(usage.get("output_tokens", 0)),
        "est_cost_usd": float(data.get("total_cost_usd") or 0),
        "model": next(iter((data.get("modelUsage") or {}).keys()), s.ai_model),
    }
    return str(data.get("result") or ""), meta


def run_json(db: Session, purpose: str, system: str, prompt: str, *, job_id: Optional[int] = None,
             use_cache: bool = True, runner=None) -> dict:
    """Run one AI call that must return a JSON object. Raises AIUnavailable when it may not/cannot run."""
    key = hashlib.sha256(f"{purpose}\x1f{system}\x1f{prompt}".encode()).hexdigest()
    if use_cache:
        hit = db.get(AICache, key)
        if hit is not None:
            db.add(AIUsage(purpose=purpose, mode="cache", cached=True, job_id=job_id))
            db.commit()
            return hit.result
    st = status(db)
    if not st["available"]:
        raise AIUnavailable(st["reason"])
    runner = runner or _run_claude_cli
    try:
        text, meta = runner(prompt, system)
    except (AIUnavailable, subprocess.TimeoutExpired, OSError) as e:
        db.add(AIUsage(purpose=purpose, mode=st["mode"], ok=False, error=str(e)[:300], job_id=job_id))
        db.commit()
        raise AIUnavailable(str(e)) from e
    result = _extract_json(text)
    db.add(AIUsage(purpose=purpose, mode=st["mode"], model=meta.get("model", ""), input_tokens=meta.get("input_tokens", 0),
                   output_tokens=meta.get("output_tokens", 0), est_cost_usd=meta.get("est_cost_usd", 0.0),
                   ok=result is not None, error="" if result is not None else "response was not JSON", job_id=job_id))
    if result is None:
        db.commit()
        raise AIUnavailable("The model did not return valid JSON.")
    existing = db.get(AICache, key)
    if existing is None:
        db.add(AICache(key=key, purpose=purpose, result=result))
    else:
        existing.result = result
    db.commit()
    return result
