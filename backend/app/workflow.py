"""Orchestration of the two browser workflows: fill-for-review and approved submit."""
from __future__ import annotations

from sqlalchemy.orm import Session

from . import automation, pipeline
from .core import emit, get_setting, notify
from .discovery import load_profile, verify_job
from .models import Application, Document
from .preparation import collect_issues, refresh_profile_answers, resolve_answer

LOCKED = ("submitted", "submitting", "submit_uncertain", "approved")


def fill_application(db: Session, application_id: int, *, runner=None) -> dict:
    """Open the real form, fill it, screenshot it and queue it for approval. Never submits."""
    runner = runner or automation.run_form
    app = db.get(Application, application_id)
    if app is None:
        return {"ok": False, "error": "application not found"}
    if app.status in LOCKED:
        return {"ok": False, "error": f"application is {app.status}"}
    job = app.job
    name = f"{job.company.name} — {job.title}"
    live = verify_job(db, job)
    db.commit()
    if live is False:
        app.status = "prepared"
        app.last_error = "The vacancy is no longer listed on the official source."
        emit(db, "form.failed", f"Form not opened, vacancy closed: {name}.", level="warn", job_id=job.id, application_id=app.id)
        db.commit()
        return {"ok": False, "error": app.last_error}
    profile = load_profile(db)
    refresh_profile_answers(db, app, profile)
    cv = db.get(Document, app.cv_document_id) if app.cv_document_id else None
    app.issues = collect_issues(app, profile, cv)
    if pipeline.blocking_issues(app):
        app.status = "prepared"
        emit(db, "form.blocked", f"Form not opened yet, input needed first: {name}.", level="warn", job_id=job.id, application_id=app.id)
        db.commit()
        return {"ok": False, "error": "blocking issues", "issues": app.issues}

    timeout = int(get_setting(db, "automation").get("max_form_seconds", 120))
    emit(db, "form.started", f"Opening application form: {name}.", job_id=job.id, application_id=app.id)
    db.commit()
    res = {}
    for attempt in (1, 2):
        res = runner(db, app, "fill", timeout_s=timeout)
        known = {a["key"] for a in app.answers or []}
        added = []
        for d in res.get("discovered") or []:
            if d["key"] in known or d.get("type") == "file":
                continue
            a = resolve_answer(d, job, profile, app.cover_letter, cv)
            a["discovered"] = True
            added.append(a)
        if not added:
            break
        app.answers = list(app.answers or []) + added
        pipeline.touch_content(db, app, "questions discovered on the live form")
        emit(db, "form.discovered", f"{len(added)} additional question(s) found on the live form: {name}.", job_id=job.id, application_id=app.id)
        db.commit()
        if attempt == 2 or not any(a.get("value") not in (None, "", []) for a in added):
            break

    app.fill_report = dict(res)
    app.issues = collect_issues(app, profile, cv)
    for u in res.get("unmapped_required") or []:
        if not any(i.get("field_label") == u["label"] for i in app.issues):
            app.issues.append({"code": "form_field", "field_label": u["label"], "blocking": True,
                               "text": f"Required form field “{u['label'] or u['type']}” could not be completed: {u['reason']}."})
    app.issues = list(app.issues)
    blocking = pipeline.blocking_issues(app)
    if res.get("needs_manual"):
        app.status = "needs_manual"
        app.last_error = res.get("error", "")
        emit(db, "form.manual", f"Manual step needed: {name}. {res.get('error', '')}", level="warn", job_id=job.id, application_id=app.id)
        notify(db, "needs_manual", f"Manual step needed: {job.title}", res.get("error", ""),
               dedupe_key=f"manual:{app.id}:{app.revision}", job_id=job.id, application_id=app.id)
    elif res.get("ok") and not blocking:
        app.status = "awaiting_approval"
        app.last_error = ""
        job.stage = "awaiting_approval"
        emit(db, "form.filled", f"Form filled and waiting for your approval: {name} ({len(res.get('filled', []))} fields).",
             job_id=job.id, application_id=app.id)
        notify(db, "awaiting_approval", f"Review & approve: {job.title}", f"{job.company.name} — the filled form is ready for your review.",
               dedupe_key=f"approve:{app.id}:{app.revision}", job_id=job.id, application_id=app.id)
    else:
        app.status = "prepared"
        app.last_error = res.get("error", "") or (f"{len(blocking)} form item(s) need your input." if blocking else "")
        emit(db, "form.failed", f"Form could not be completed: {name}. {app.last_error}", level="warn", job_id=job.id, application_id=app.id)
        notify(db, "form_error", f"Form needs attention: {job.title}", app.last_error,
               dedupe_key=f"formerr:{app.id}:{app.revision}", job_id=job.id, application_id=app.id)
    db.commit()
    return {"ok": app.status == "awaiting_approval", "status": app.status, "report": res}


def submit_application(db: Session, application_id: int, submit_key: str, *, runner=None) -> dict:
    """Submit an approved application exactly once."""
    runner = runner or automation.run_form
    app = pipeline.begin_submit(db, application_id, submit_key)
    if app is None:
        return {"ok": False, "error": "submission not authorised for the current version"}
    job = app.job
    emit(db, "submit.started", f"Submitting approved application: {job.company.name} — {job.title}.", job_id=job.id, application_id=app.id)
    db.commit()
    try:
        live = verify_job(db, job)
        db.commit()
        if live is False:
            pipeline.finish_submit(db, app, "failed_before_send", error="The vacancy closed before submission.")
            return {"ok": False, "error": "vacancy closed"}
        expected = {x["key"] for x in (app.fill_report or {}).get("filled", [])}
        timeout = int(get_setting(db, "automation").get("max_form_seconds", 120)) + 60
        res = runner(db, app, "submit", timeout_s=timeout, expect_filled=expected)
    except Exception as e:  # the runner itself reports click state; anything escaping it happened before a click
        pipeline.finish_submit(db, app, "failed_before_send", error=f"{type(e).__name__}: {e}")
        return {"ok": False, "error": str(e)}
    outcome = res.get("outcome") or "uncertain"
    if outcome not in ("submitted", "failed_before_send", "uncertain"):
        outcome = "uncertain"
    confirmation = {k: res.get(k) for k in ("final_url", "confirmation_text", "clicked_at", "finished_at", "screenshots") if res.get(k)}
    pipeline.finish_submit(db, app, outcome, confirmation=confirmation, error=res.get("error", ""))
    return {"ok": outcome == "submitted", "outcome": outcome, "error": res.get("error", "")}
