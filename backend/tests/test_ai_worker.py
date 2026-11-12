import json
from datetime import timedelta

import pytest
from sqlalchemy import select

from app import ai, preparation, worker
from app.config import get_settings
from app.core import enqueue, get_setting, set_setting
from app.db import utcnow
from app.models import AIUsage, Company, Event, Task


def enable_ai(db, monkeypatch, **cfg):
    monkeypatch.setattr(get_settings(), "ai_mode", "claude_cli")
    c = get_setting(db, "ai")
    c.update({"enabled": True, **cfg})
    set_setting(db, "ai", c)
    db.commit()


def test_ai_is_off_by_default_and_needs_both_switches(db, monkeypatch):
    assert ai.status(db)["available"] is False
    with pytest.raises(ai.AIUnavailable):
        ai.run_json(db, "x", "sys", "prompt", runner=lambda p, s: ("{}", {}))
    monkeypatch.setattr(get_settings(), "ai_mode", "claude_cli")
    assert "switched off in Settings" in ai.status(db)["reason"]
    enable_ai(db, monkeypatch)
    assert ai.status(db)["available"] is True


def test_ai_budget_cache_and_usage_tracking(db, monkeypatch):
    enable_ai(db, monkeypatch, daily_call_budget=2)
    calls = []

    def runner(prompt, system):
        calls.append(prompt)
        return '```json\n{"ok": true}\n```', {"input_tokens": 100, "output_tokens": 20, "est_cost_usd": 0.01, "model": "haiku"}

    assert ai.run_json(db, "t", "s", "p1", runner=runner) == {"ok": True}
    assert ai.run_json(db, "t", "s", "p1", runner=runner) == {"ok": True}  # cached, no second call
    assert len(calls) == 1
    ai.run_json(db, "t", "s", "p2", runner=runner)
    with pytest.raises(ai.AIUnavailable) as e:
        ai.run_json(db, "t", "s", "p3", runner=runner)
    assert "budget" in str(e.value) and len(calls) == 2
    u = ai.usage_summary(db)
    assert u["today"]["calls"] == 2 and u["today"]["est_cost_usd"] == 0.02 and u["cache_hits"] == 1


def test_ai_non_json_is_an_error_not_data(db, monkeypatch):
    enable_ai(db, monkeypatch)
    with pytest.raises(ai.AIUnavailable):
        ai.run_json(db, "t", "s", "p", runner=lambda p, s: ("I think this job is great!", {}))
    assert db.query(AIUsage).filter_by(ok=False).count() == 1


def test_ai_evaluation_cannot_invent_visa_evidence(db, job_factory, monkeypatch):
    enable_ai(db, monkeypatch)
    job = job_factory(description="Build APIs. Our team is friendly and we help newcomers settle into Berlin life.")
    assert job.visa_status == "unverified"
    fake = {"visa_status": "confirmed", "visa_quote": "We sponsor visas for all hires.", "experience_ok": "yes", "degree_blocker": "no",
            "language_blocker": "no", "notes": "n", "fit_stars": 5, "fit_reason": "great"}
    monkeypatch.setattr(ai, "_run_claude_cli", lambda p, s, timeout=180: (json.dumps(fake), {"est_cost_usd": 0.0}))
    assert preparation.ai_evaluate_job(db, job) is True
    assert job.visa_status == "unverified"  # quote is not in the posting -> classification unchanged
    assert any(e["kind"] == "ai" and "no verifiable quote" in e["explanation"] for e in job.visa_evidence)
    assert job.analysis_source == "ai" and any(r["kind"] == "ai" for r in job.eligibility_reasons)


def test_ai_evaluation_accepts_verbatim_quote(db, job_factory, monkeypatch):
    enable_ai(db, monkeypatch)
    job = job_factory(description="Build APIs. Newcomers from abroad get their residence paperwork handled by our people team.")
    fake = {"visa_status": "confirmed", "visa_quote": "Newcomers from abroad get their residence paperwork handled by our people team.",
            "experience_ok": "yes", "degree_blocker": "no", "language_blocker": "no", "notes": "", "fit_stars": 4, "fit_reason": "ok"}
    monkeypatch.setattr(ai, "_run_claude_cli", lambda p, s, timeout=180: (json.dumps(fake), {}))
    preparation.ai_evaluate_job(db, job)
    assert job.visa_status == "confirmed" and job.visa_evidence[0]["quote"] in job.description_text


def test_ai_materials_used_only_when_available(db, job_factory, cv, monkeypatch):
    job = job_factory()
    app = preparation.prepare_application(db, job, use_ai=True)
    assert app.materials_source == "template" and db.query(AIUsage).count() == 0  # AI off -> no call, still useful
    enable_ai(db, monkeypatch)
    out = {"cover_letter": "Dear Acme team,\n\nShort and factual.\n\nKind regards,\nTest Candidate", "fit_pitch": "Fits.", "answers": {}}
    monkeypatch.setattr(ai, "_run_claude_cli", lambda p, s, timeout=180: (json.dumps(out), {"est_cost_usd": 0.004}))
    app = preparation.prepare_application(db, job, use_ai=True)
    assert app.materials_source == "ai" and app.cover_letter.startswith("Dear Acme team") and app.revision == 2


def test_worker_runs_tasks_with_bounded_retries(db, monkeypatch):
    seen = []
    monkeypatch.setitem(worker.HANDLERS, "ok", lambda db, p: seen.append(p) or {"done": 1})

    def bad(db, p):
        raise RuntimeError("nope")

    monkeypatch.setitem(worker.HANDLERS, "bad", bad)
    enqueue(db, "ok", {"a": 1})
    t_bad = enqueue(db, "bad", {}, max_attempts=2)
    db.commit()
    assert worker.run_one(db).status == "done" and seen == [{"a": 1}]
    assert worker.run_one(db).status == "queued"  # first failure -> one retry, delayed
    assert worker.run_one(db) is None
    db.get(Task, t_bad.id).run_after = utcnow() - timedelta(seconds=1)
    db.commit()
    assert worker.run_one(db).status == "failed"
    assert worker.run_one(db) is None
    assert db.get(Task, t_bad.id).attempts == 2
    assert db.scalar(select(Event).where(Event.type == "task.failed")) is not None


def test_dedupe_key_prevents_duplicate_queueing(db):
    a = enqueue(db, "discovery", {}, dedupe_key="discovery")
    b = enqueue(db, "discovery", {}, dedupe_key="discovery")
    assert a.id == b.id


def test_scheduler_respects_dashboard_settings(db):
    db.add(Company(name="A", provider="lever", board_token="a"))
    db.commit()
    assert "discovery" in worker.scheduler_tick(db)
    assert "discovery" not in worker.scheduler_tick(db)  # already queued
    db.query(Task).delete()
    runs = {"discovery": {"at": utcnow().isoformat() + "Z"}, "verify": {"at": utcnow().isoformat() + "Z"}}
    set_setting(db, "last_runs", runs)
    db.commit()
    assert worker.scheduler_tick(db) == []
    runs["discovery"]["at"] = (utcnow() - timedelta(hours=13)).isoformat() + "Z"
    set_setting(db, "last_runs", runs)
    db.commit()
    assert worker.scheduler_tick(db) == ["discovery"]
    db.query(Task).delete()
    s = get_setting(db, "schedule")
    s["discovery_enabled"] = False
    set_setting(db, "schedule", s)
    db.commit()
    assert worker.scheduler_tick(db) == []
