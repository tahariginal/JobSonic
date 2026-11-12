"""Browser automation for application forms (Playwright, headless Chromium).

Rules enforced here:
  * one browser at a time, always closed afterwards, fresh context (no cookies kept);
  * CAPTCHA / login walls are detected and reported, never bypassed;
  * `fill` mode never clicks a submit button;
  * `submit` mode only runs after pipeline.begin_submit() granted it, fills exactly the approved
    answers, and reports one of: submitted / failed_before_send / uncertain.
"""
from __future__ import annotations

import logging
import re
import secrets
import time
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from .config import get_settings
from .db import utcnow
from .models import Application, Document, Screenshot
from .preparation import classify_field

log = logging.getLogger("sonic.automation")

CLOSED_TEXT = re.compile(
    r"no longer (open|available|accepting|active|posted)|(job|position|role|posting) (has been|was|is) (closed|filled|removed|no longer)|"
    r"position (has been )?filled|this job is closed|job not found|page not found|posting.*not.*found|isn.t available anymore|"
    r"the job you are looking for|job board you were viewing is no longer active",
    re.I,
)
CONFIRM_TEXT = re.compile(
    r"thank you for (applying|your application|your interest)|thanks for applying|application (has been |was )?(successfully )?(received|submitted|sent)|"
    r"we(.ve| have) received your application|successfully (applied|submitted)|your application is on its way|application complete",
    re.I,
)
HUMAN_CHECK = re.compile(r"verify (that )?you are (a )?human|are you a robot|unusual traffic|complete the security check|checking your browser", re.I)

ENUMERATE_JS = r"""
() => {
  const vis = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return s.visibility !== 'hidden' && s.display !== 'none' && (r.width > 0 || r.height > 0 || el.type === 'file'); };
  const clean = (t) => (t || '').replace(/\s+/g, ' ').replace(/\s*[*✱]\s*$/, '').trim();
  const labelFor = (el) => {
    if (el.id) { const l = document.querySelector('label[for="' + CSS.escape(el.id) + '"]'); if (l) return l.innerText; }
    const al = el.getAttribute('aria-labelledby');
    if (al) { const t = al.split(/\s+/).map(i => (document.getElementById(i) || {}).innerText || '').join(' '); if (t.trim()) return t; }
    if (el.getAttribute('aria-label')) return el.getAttribute('aria-label');
    const wrap = el.closest('label'); if (wrap) return wrap.innerText;
    let n = el.parentElement;
    for (let i = 0; i < 5 && n; i++, n = n.parentElement) {
      const l = n.querySelector(':scope > label, :scope > legend, :scope > .label, :scope > div > label, :scope > [class*="label" i]:not(input)');
      if (l && l.innerText && l.innerText.trim() && !l.contains(el)) return l.innerText;
      if (n.tagName === 'FORM') break;
    }
    return el.getAttribute('placeholder') || el.name || '';
  };
  const groupLabel = (el) => {
    const fs = el.closest('fieldset'); if (fs) { const lg = fs.querySelector('legend'); if (lg) return lg.innerText; }
    let n = el.parentElement;
    for (let i = 0; i < 6 && n; i++, n = n.parentElement) {
      const l = n.querySelector(':scope > label, :scope > legend, :scope > .label, :scope > [class*="label" i]:not(input), :scope > .application-label, :scope > div.text');
      if (l && l.innerText && !l.contains(el) && n.querySelectorAll('input[type=radio],input[type=checkbox]').length > 1) return l.innerText;
      if (n.tagName === 'FORM') break;
    }
    return '';
  };
  const out = []; const groups = {}; let i = 0;
  const els = Array.from(document.querySelectorAll('input, textarea, select'));
  for (const el of els) {
    const type = (el.getAttribute('type') || el.tagName).toLowerCase();
    if (['hidden', 'submit', 'button', 'image', 'reset', 'search'].includes(type)) continue;
    if (el.disabled) continue;
    if (!vis(el) && type !== 'file' && type !== 'radio' && type !== 'checkbox') continue;
    if (el.closest('[aria-hidden="true"]') && type !== 'file') continue;
    const sid = 'sj' + (i++); el.setAttribute('data-sj', sid);
    const req = el.required || el.getAttribute('aria-required') === 'true';
    if (type === 'radio' || type === 'checkbox') {
      const gl = groupLabel(el); const own = clean(labelFor(el));
      const many = el.name && document.querySelectorAll('input[name="' + CSS.escape(el.name) + '"]').length > 1;
      if (type === 'radio' || (many && gl)) {
        const gk = type + ':' + (el.name || gl);
        if (!groups[gk]) { groups[gk] = { sid, tag: 'group', type, name: el.name || '', id: '', label: clean(gl) || own, required: req || /\*\s*$/.test(gl || ''), options: [], optionIds: [] }; out.push(groups[gk]); }
        groups[gk].options.push(own); groups[gk].optionIds.push(sid);
        continue;
      }
      out.push({ sid, tag: 'input', type: 'checkbox', name: el.name || '', id: el.id || '', label: own, required: req, options: [] });
      continue;
    }
    const raw = labelFor(el);
    const role = el.getAttribute('role') || '';
    const combo = role === 'combobox' || el.getAttribute('aria-autocomplete') === 'list' || el.getAttribute('aria-haspopup') === 'listbox';
    out.push({ sid, tag: el.tagName.toLowerCase(), type: el.tagName === 'SELECT' ? 'select' : (el.tagName === 'TEXTAREA' ? 'textarea' : (combo ? 'combobox' : type)),
      name: el.name || '', id: el.id || '', label: clean(raw), required: req || /[*✱]\s*$/.test((raw || '').trim()),
      options: el.tagName === 'SELECT' ? Array.from(el.options).map(o => o.text.trim()).filter(t => t && !/^(select|choose|--|please select)/i.test(t)) : [],
      accept: el.getAttribute('accept') || '' });
  }
  return out;
}
"""


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _sim(a: str, b: str) -> float:
    ta, tb = set(_norm(a).split()), set(_norm(b).split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def match_fields(answers: list[dict], dom: list[dict]) -> dict[str, dict]:
    """Map answer key -> DOM field. Key match first, then label, then well-known field kind."""
    used: set[str] = set()
    mapping: dict[str, dict] = {}

    def take(a, f):
        mapping[a["key"]] = f
        used.add(f["sid"])

    for a in answers:
        k = a.get("key", "")
        for f in dom:
            if f["sid"] not in used and k and (f["name"] == k or f["id"] == k or f["name"] == f"{k}[]"):
                take(a, f)
                break
    for a in answers:
        if a["key"] in mapping or not a.get("label"):
            continue
        best, score = None, 0.0
        for f in dom:
            if f["sid"] in used:
                continue
            s = 1.0 if _norm(f["label"]) == _norm(a["label"]) else _sim(f["label"], a["label"])
            if s > score:
                best, score = f, s
        if best is not None and score >= 0.72:
            take(a, best)
    for a in answers:
        if a["key"] in mapping:
            continue
        kind = a.get("kind") or classify_field(a.get("label", ""), a.get("key", ""))
        if kind in ("custom", "why", "about", "projects", "consent", "demographic"):
            continue
        cands = [f for f in dom if f["sid"] not in used and classify_field(f["label"], f["name"] or f["id"]) == kind]
        if kind in ("resume", "cover_letter"):
            cands = [f for f in cands if (f["type"] == "file") == (a.get("type") == "file")]
        if len(cands) == 1:
            take(a, cands[0])
    return mapping


class FormRunResult(dict):
    pass


def _detect_blockers(page) -> dict:
    out = {"captcha": False, "login": False, "recaptcha_present": False}
    try:
        out["recaptcha_present"] = page.locator('iframe[src*="recaptcha"], .grecaptcha-badge, iframe[src*="hcaptcha"], [class*="turnstile"]').count() > 0
        challenge = page.locator('iframe[src*="recaptcha/api2/bframe"], iframe[src*="recaptcha/enterprise/bframe"], iframe[src*="hcaptcha.com/captcha"], iframe[title*="challenge" i]')
        for i in range(min(challenge.count(), 4)):
            if challenge.nth(i).is_visible():
                box = challenge.nth(i).bounding_box()
                if box and box["width"] > 100 and box["height"] > 100:
                    out["captcha"] = True
        body = page.inner_text("body", timeout=3000)[:4000]
        if HUMAN_CHECK.search(body):
            out["captcha"] = True
        if page.locator('input[type=password]:visible').count() > 0:
            out["login"] = True
    except Exception:
        pass
    return out


def _fill_one(page, f: dict, a: dict, cv_path: Optional[str]) -> tuple[bool, str]:
    """Fill a single field. Returns (ok, detail)."""
    value = a.get("value")
    loc = page.locator(f'[data-sj="{f["sid"]}"]')
    t = f["type"]
    try:
        if t == "file":
            if a.get("kind") == "resume" or isinstance(value, dict):
                if not cv_path:
                    return False, "no CV file available"
                loc.set_input_files(cv_path)
                return True, Path(cv_path).name
            return False, "file upload not supported for this field"
        if value in (None, "", []):
            return False, "no value"
        if f["tag"] == "group":
            wanted = [value] if not isinstance(value, list) else value
            done = []
            for w in wanted:
                idx = next((i for i, o in enumerate(f["options"]) if _norm(o) == _norm(str(w))), None)
                if idx is None:
                    idx = next((i for i, o in enumerate(f["options"]) if _norm(str(w)) and _norm(o).startswith(_norm(str(w)))), None)
                if idx is None:
                    return False, f"option “{w}” not found"
                page.locator(f'[data-sj="{f["optionIds"][idx]}"]').check(force=True)
                done.append(f["options"][idx])
            return True, ", ".join(done)
        if t == "checkbox":
            truthy = value is True or str(value).strip().lower() in ("true", "yes", "1", "on", "i agree", "agree")
            if truthy:
                loc.check(force=True)
            return True, "checked" if truthy else "left unchecked"
        if t == "select":
            opt = next((o for o in f["options"] if _norm(o) == _norm(str(value))), None) or \
                next((o for o in f["options"] if _norm(o).startswith(_norm(str(value)))), None)
            if opt is None:
                return False, f"option “{value}” not found"
            loc.select_option(label=opt)
            return True, opt
        if t == "combobox":
            loc.click()
            loc.fill(str(value))
            page.wait_for_timeout(700)
            option = page.locator('[role="option"]').filter(has_text=re.compile(re.escape(str(value)), re.I)).first
            if option.count() == 0:
                loc.fill("")
                page.keyboard.press("Escape")
                return False, f"no dropdown option matching “{value}”"
            text = option.inner_text()
            option.click()
            return True, text.strip()[:80]
        loc.fill(str(value))
        got = loc.input_value()
        return (got.strip() == str(value).strip()), ("ok" if got.strip() == str(value).strip() else "value did not stick")
    except Exception as e:  # field-level failures are reported, not fatal
        return False, f"{type(e).__name__}: {str(e)[:120]}"


def _save_shot(db: Session, app: Application, page, kind: str) -> Optional[str]:
    s = get_settings()
    name = f"app{app.id}-r{app.revision}-{kind}-{secrets.token_hex(6)}.png"
    try:
        page.screenshot(path=str(s.screenshots_dir / name), full_page=True, timeout=20000)
    except Exception:
        try:
            page.screenshot(path=str(s.screenshots_dir / name), timeout=10000)
        except Exception:
            return None
    try:
        (s.screenshots_dir / name).chmod(0o600)
    except OSError:
        pass
    db.add(Screenshot(application_id=app.id, revision=app.revision, kind=kind, stored_name=name))
    db.commit()
    return name


def run_form(db: Session, app: Application, mode: str = "fill", *, headless: bool = True, timeout_s: int = 120,
             expect_filled: Optional[set] = None) -> FormRunResult:
    """Open the official form, fill it, screenshot it; in submit mode press the final button once."""
    from playwright.sync_api import TimeoutError as PWTimeout
    from playwright.sync_api import sync_playwright

    assert mode in ("fill", "submit")
    settings = get_settings()
    form_url = (app.form_schema or {}).get("form_url") or app.job.apply_url
    cv = db.get(Document, app.cv_document_id) if app.cv_document_id else None
    cv_path = str(settings.uploads_dir / cv.stored_name) if cv else None
    res = FormRunResult(mode=mode, form_url=form_url, started_at=utcnow().isoformat() + "Z", ok=False, outcome="",
                        filled=[], unfilled=[], unmapped_required=[], discovered=[], blockers={}, screenshots=[], error="",
                        revision=app.revision, content_hash=app.content_hash)
    deadline = time.monotonic() + timeout_s
    answers = [a for a in (app.answers or []) if a.get("type") != "info"]

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless, args=["--disable-dev-shm-usage", "--no-default-browser-check"])
        try:
            ctx = browser.new_context(viewport={"width": 1280, "height": 1600}, accept_downloads=False,
                                      user_agent=None, locale="en-US")
            ctx.set_default_timeout(15000)
            page = ctx.new_page()
            try:
                resp = page.goto(form_url, wait_until="domcontentloaded", timeout=45000)
            except PWTimeout:
                res["error"] = "The application page did not load in time."
                res["outcome"] = "failed_before_send"
                return res
            try:
                page.wait_for_load_state("networkidle", timeout=12000)
            except PWTimeout:
                pass
            status = resp.status if resp else 0
            try:
                page.wait_for_selector("input[type=file], input[type=email], form input, form textarea", timeout=12000, state="attached")
            except PWTimeout:
                pass
            body_text = ""
            try:
                body_text = page.inner_text("body", timeout=5000)
            except Exception:
                pass
            res["final_url"] = page.url
            res["blockers"] = _detect_blockers(page)
            dom = page.evaluate(ENUMERATE_JS)
            if status in (404, 410) or (CLOSED_TEXT.search(body_text[:3000]) and len(dom) < 3):
                res["error"] = "The vacancy appears to be closed (the application page is gone)."
                res["closed"] = True
                res["outcome"] = "failed_before_send"
                res["screenshots"].append(_save_shot(db, app, page, "error"))
                return res
            if res["blockers"]["captcha"] or (res["blockers"]["login"] and len(dom) < 4):
                res["error"] = "The site asked for a human check or login. This needs you to continue manually."
                res["needs_manual"] = True
                res["outcome"] = "failed_before_send"
                res["screenshots"].append(_save_shot(db, app, page, "error"))
                return res
            if len(dom) < 2:
                res["error"] = "No application form was found on the page."
                res["needs_manual"] = True
                res["outcome"] = "failed_before_send"
                res["screenshots"].append(_save_shot(db, app, page, "error"))
                return res

            mapping = match_fields(answers, dom)
            mapped_sids = {f["sid"] for f in mapping.values()}
            for a in answers:
                f = mapping.get(a["key"])
                if f is None:
                    if a.get("value") not in (None, "", []) and a.get("source") != "skipped":
                        res["unfilled"].append({"key": a["key"], "label": a.get("label", ""), "reason": "field not found on the page"})
                    continue
                if a.get("source") == "skipped" or (a.get("value") in (None, "", []) and f["type"] != "file"):
                    if f["required"]:
                        res["unmapped_required"].append({"label": f["label"], "type": f["type"], "reason": "no answer prepared"})
                    continue
                ok, detail = _fill_one(page, f, a, cv_path)
                if ok:
                    res["filled"].append({"key": a["key"], "label": f["label"] or a.get("label", ""), "detail": detail})
                else:
                    res["unfilled"].append({"key": a["key"], "label": f["label"] or a.get("label", ""), "reason": detail})
                    if f["required"]:
                        res["unmapped_required"].append({"label": f["label"], "type": f["type"], "reason": detail})
                if time.monotonic() > deadline:
                    res["error"] = "Form filling exceeded the time limit."
                    res["outcome"] = "failed_before_send"
                    return res

            # fields on the page that the prepared answers do not cover
            for f in dom:
                if f["sid"] in mapped_sids:
                    continue
                entry = {"key": f["name"] or f["id"] or f"dom:{_norm(f['label'])[:60]}", "label": f["label"],
                         "type": {"group": "select" if f["type"] == "radio" else "multiselect"}.get(f["tag"], f["type"]) if f["tag"] == "group" else f["type"],
                         "required": bool(f["required"]), "options": f.get("options") or []}
                if not entry["label"] and not entry["required"]:
                    continue
                res["discovered"].append(entry)
                if f["required"]:
                    res["unmapped_required"].append({"label": f["label"], "type": f["type"], "reason": "question was not in the prepared answers"})

            page.wait_for_timeout(600)
            res["screenshots"].append(_save_shot(db, app, page, "filled" if mode == "fill" else "pre_submit"))

            if mode == "fill":
                res["ok"] = True
                res["outcome"] = "filled"
                return res

            # ---------------- submit mode ----------------
            filled_keys = {x["key"] for x in res["filled"]}
            if res["unmapped_required"] or (expect_filled is not None and filled_keys != set(expect_filled)):
                res["error"] = "The live form no longer matches the approved answers; nothing was sent."
                res["outcome"] = "failed_before_send"
                return res
            if not settings.allow_real_submit:
                res["error"] = "Real submission is disabled on this server (SONIC_ALLOW_REAL_SUBMIT=false)."
                res["outcome"] = "failed_before_send"
                return res
            btn = page.locator('button[type=submit]:visible, input[type=submit]:visible').first
            if btn.count() == 0:
                btn = page.get_by_role("button", name=re.compile(r"^(submit( application)?|send application|apply( now)?)$", re.I)).first
            if btn.count() == 0:
                res["error"] = "Could not find the submit button; nothing was sent."
                res["outcome"] = "failed_before_send"
                return res
            url_before = page.url
            res["clicked_at"] = utcnow().isoformat() + "Z"
            btn.click()
            # from here on we can no longer claim "nothing was sent" unless the page proves it
            confirmed, invalid, captcha = False, False, False
            end = time.monotonic() + 25
            while time.monotonic() < end:
                page.wait_for_timeout(1000)
                try:
                    text = page.inner_text("body", timeout=4000)
                except Exception:
                    text = ""
                if CONFIRM_TEXT.search(text) or re.search(r"confirmation|thank|success|submitted", page.url.replace(url_before, ""), re.I):
                    confirmed = True
                    res["confirmation_text"] = (CONFIRM_TEXT.search(text).group(0) if CONFIRM_TEXT.search(text) else "")[:200]
                    break
                if _detect_blockers(page)["captcha"]:
                    captcha = True
                    break
                try:
                    invalid = page.locator('[aria-invalid="true"]:visible, .error:visible, [class*="error" i][role="alert"]:visible, input:invalid').count() > 0
                except Exception:
                    invalid = False
                if invalid and page.url == url_before:
                    break
            res["final_url"] = page.url
            res["screenshots"].append(_save_shot(db, app, page, "confirmation" if confirmed else "error"))
            if confirmed:
                res["ok"] = True
                res["outcome"] = "submitted"
            elif captcha:
                res["error"] = "A CAPTCHA appeared when submitting. It was not bypassed; nothing is confirmed as sent."
                res["needs_manual"] = True
                res["outcome"] = "failed_before_send"
            elif invalid:
                res["error"] = "The form reported validation errors and stayed on the same page; nothing was sent."
                res["outcome"] = "failed_before_send"
            else:
                res["error"] = "The submit button was pressed but no confirmation page was detected."
                res["outcome"] = "uncertain"
            return res
        except Exception as e:
            log.exception("form run failed")
            res["error"] = f"{type(e).__name__}: {str(e)[:300]}"
            res["outcome"] = "uncertain" if res.get("clicked_at") else "failed_before_send"
            return res
        finally:
            res["finished_at"] = utcnow().isoformat() + "Z"
            res["screenshots"] = [s for s in res["screenshots"] if s]
            try:
                browser.close()
            except Exception:
                pass
