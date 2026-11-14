"""Background worker: a single process that drains the task queue and runs the scheduler.

One task at a time (so at most one browser), bounded attempts, no unlimited retry loops.
Submissions are never retried automatically.
"""
from __future__ import annotations

import logging
import signal
import time
from datetime import datetime, timedelta
from typing import Callable, Optional

from sqlalchemy import case, or_, select, update
from sqlalchemy.orm import Session

from . import emailing, pipeline, preparation, workflow
from .core import emit, enqueue, get_setting, set_setting
from .db import SessionLocal, utcnow
from .discovery import reanalyze_all, run_discovery, verify_job
from .models import Application, Company, Event, Job, Notification, Task

log = logging.getLogger("sonic.worker")


def t_discovery(db: Session, p: dict) -> dict:
    started = utcnow()
    out = run_discovery(db, company_ids=p.get("company_ids"), trigger=p.get("trigger", "schedule"))
    cfg = get_setting(db, "ai")
    if cfg.get("enabled") and cfg.get("auto_evaluate"):
        for jid in out.get("new_ids", []):
            job = db.get(Job, jid)
            if job and job.eligibility != "rejected" and job.fit_stars >= int(cfg.get("min_stars_for_ai", 4)):
                enqueue(db, "ai_evaluate", {"job_id": jid}, dedupe_key=f"ai:{jid}")
        db.commit()
    if not p.get("company_ids"):
        out["automatic_submissions"] = queue_ready_submissions(db, verified_since=started)
        out["auto_applications"] = queue_auto_applications(db, verified_since=started)
    out.pop("new_ids", None)
    return out


def queue_ready_submissions(db: Session, *, verified_since: datetime) -> int:
    """Resume filled automatic applications under the current policy after a full refresh."""
    cfg = get_setting(db, "automation")
    if not cfg.get("auto_fill_enabled") or not cfg.get("auto_submit_enabled"):
        return 0
    applications = db.scalars(select(Application).join(Job, Application.job_id == Job.id)
                             .where(Application.status == "awaiting_approval", Application.automation_mode == "automatic",
                                    Job.last_verified_at >= verified_since)
                             .order_by(Job.fit_score.desc(), Job.id))
    queued = 0
    limit = max(1, min(100, int(cfg["max_applications_per_cycle"])))
    for application in applications:
        if pipeline.automatic_submission_reason(db, application):
            continue
        try:
            pipeline.approve(db, application, application.revision, application.content_hash, automatic=True)
        except pipeline.PipelineError:
            # Stale content returns to preparation without stopping independent applications.
            continue
        queued += 1
        if queued >= limit:
            break
    if queued:
        emit(db, "autosubmit.queued", f"Queued {queued} completed automatic applications to submit, highest fit first.",
             data={"queued": queued})
    db.commit()
    return queued


def queue_auto_applications(db: Session, *, verified_since: datetime) -> int:
    """Reserve fresh eligible jobs, then queue preparation and filling, never submission."""
    cfg = get_setting(db, "automation")
    if not cfg.get("auto_fill_enabled"):
        return 0
    limit = max(1, min(100, int(cfg["max_applications_per_cycle"])))
    stmt = (select(Job).join(Company, Company.id == Job.company_id)
            .outerjoin(Application, Application.job_id == Job.id)
            .where(Application.id.is_(None), Company.enabled.is_(True), Job.is_active.is_(True),
                   Job.eligibility == "eligible", Job.stage.in_(("discovered", "verified", "shortlisted")),
                   Job.last_verified_at >= verified_since))
    if not cfg.get("include_other_matches"):
        stmt = stmt.where(or_(Job.visa_status == "confirmed", Job.remote_mode == "remote"))
    priority = case((Job.visa_status == "confirmed", 0), (Job.remote_mode == "remote", 1), else_=2)
    jobs = list(db.scalars(stmt.order_by(Job.fit_score.desc(), priority, Job.discovered_at.desc(), Job.id).limit(limit)))
    counts = {"visa_confirmed": 0, "remote": 0, "other": 0}
    for job in jobs:
        application = Application(job=job, status="draft", revision=0, automation_mode="automatic")
        db.add(application)
        job.stage = "preparing"
        db.flush()
        enqueue(db, "prepare_application", {"job_id": job.id, "application_id": application.id,
                "then_fill": True, "automatic": True}, dedupe_key=f"prepare:{job.id}")
        category = "visa_confirmed" if job.visa_status == "confirmed" else "remote" if job.remote_mode == "remote" else "other"
        counts[category] += 1
        emit(db, "autofill.queued", f"Automatic application queued: {job.company.name} — {job.title}.",
             job_id=job.id, application_id=application.id, data={"priority": category})
    runs = get_setting(db, "last_runs") or {}
    runs["autofill"] = {"at": utcnow().isoformat() + "Z", "queued": len(jobs), **counts}
    set_setting(db, "last_runs", runs)
    emit(db, "autofill.cycle", f"Search-to-fill cycle queued {len(jobs)} applications: {counts['visa_confirmed']} visa-confirmed, "
         f"{counts['remote']} remote, {counts['other']} other eligible matches. "
         + ("Completed forms submit automatically." if cfg.get("auto_submit_enabled") else "Submission waits for approval."),
         data=runs["autofill"])
    db.commit()
    return len(jobs)


def automatic_skip_reason(db: Session, job: Job) -> str:
    if not get_setting(db, "automation").get("auto_fill_enabled"):
        return "Automatic filling is paused in Settings."
    if not job.company.enabled or not job.is_active or job.eligibility != "eligible" or job.stage in ("archived", "rejected"):
        return "This job no longer meets the automatic application criteria. Review it manually."
    return ""


def t_verify_open(db: Session, p: dict) -> dict:
    """Re-verify jobs the user is actively working on (shortlisted .. awaiting approval)."""
    jobs = list(db.scalars(select(Job).where(Job.stage.in_(("shortlisted", "preparing", "awaiting_approval")), Job.is_active.is_(True))))
    closed = 0
    for job in jobs[:60]:
        if verify_job(db, job) is False:
            closed += 1
        db.commit()
    runs = get_setting(db, "last_runs") or {}
    runs["verify"] = {"at": utcnow().isoformat() + "Z", "checked": len(jobs[:60]), "closed": closed}
    set_setting(db, "last_runs", runs)
    return {"checked": len(jobs[:60]), "closed": closed}


def t_prepare(db: Session, p: dict) -> dict:
    job = db.get(Job, p["job_id"])
    if job is None:
        return {"error": "job not found"}
    if p.get("automatic"):
        existing = db.scalar(select(Application).where(Application.job_id == job.id))
        if existing is not None and existing.automation_mode != "automatic":
            return {"skipped": "Application switched to manual mode."}
        if existing is not None and existing.status != "draft":
            return {"skipped": "Application already prepared or reviewed."}
        reason = automatic_skip_reason(db, job)
        if reason:
            if existing is not None:
                existing.last_error = reason
            return {"skipped": reason}
    app = preparation.prepare_application(db, job, use_ai=False if p.get("automatic") else p.get("use_ai", True))
    db.commit()
    if p.get("then_fill") and not pipeline.blocking_issues(app):
        enqueue(db, "fill_form", {"application_id": app.id, "automatic": bool(p.get("automatic"))}, dedupe_key=f"fill:{app.id}")
    return {"application_id": app.id, "status": app.status}


def t_fill(db: Session, p: dict) -> dict:
    if p.get("automatic"):
        application = db.get(Application, p["application_id"])
        if application is None:
            return {"error": "application not found"}
        if application.automation_mode != "automatic":
            return {"skipped": "Application switched to manual mode."}
        if application.status != "prepared":
            return {"skipped": "Application already filled or reviewed."}
        reason = automatic_skip_reason(db, application.job)
        if reason:
            application.last_error = reason
            return {"skipped": reason}
    r = workflow.fill_application(db, p["application_id"], automatic=bool(p.get("automatic")))
    r.pop("report", None)
    return r


def t_submit(db: Session, p: dict) -> dict:
    return workflow.submit_application(db, p["application_id"], p["submit_key"], automatic=bool(p.get("automatic")))


def t_ai_evaluate(db: Session, p: dict) -> dict:
    job = db.get(Job, p["job_id"])
    return {"ok": preparation.ai_evaluate_job(db, job) if job else False}


def t_email_sync(db: Session, p: dict) -> dict:
    out = emailing.sync_all(db)
    runs = get_setting(db, "last_runs") or {}
    runs["email_sync"] = {"at": utcnow().isoformat() + "Z"}
    set_setting(db, "last_runs", runs)
    return out


def t_telegram(db: Session, p: dict) -> dict:
    n = db.get(Notification, p["notification_id"])
    if n is None:
        return {"ok": False}
    return {"ok": emailing.telegram_send(db, f"SONIC JOBS · {n.title}\n{n.body}".strip())}


def t_reanalyze(db: Session, p: dict) -> dict:
    return {"jobs": reanalyze_all(db)}


HANDLERS: dict[str, Callable[[Session, dict], dict]] = {
    "discovery": t_discovery, "verify_open": t_verify_open, "prepare_application": t_prepare, "fill_form": t_fill,
    "submit_application": t_submit, "ai_evaluate": t_ai_evaluate, "email_sync": t_email_sync,
    "telegram_send": t_telegram, "reanalyze": t_reanalyze,
}
NEVER_RETRY = {"submit_application"}


def recover(db: Session) -> None:
    """Run at startup: fail interrupted tasks; anything caught mid-submit becomes 'uncertain'."""
    stuck = list(db.scalars(select(Task).where(Task.status == "running")))
    for t in stuck:
        if t.type in NEVER_RETRY or t.attempts >= t.max_attempts:
            t.status, t.error, t.finished_at = "failed", "interrupted by a service restart", utcnow()
        else:
            t.status = "queued"
    n = pipeline.recover_interrupted(db)
    if stuck or n:
        emit(db, "worker.recovered", f"Worker restarted: {len(stuck)} interrupted task(s) handled, {n} submission(s) flagged for manual check.", level="warn")
    db.commit()


def run_one(db: Session) -> Optional[Task]:
    """Claim and execute the next due task. Returns it, or None when the queue is empty."""
    now = utcnow()
    task = db.scalar(select(Task).where(Task.status == "queued", Task.run_after <= now).order_by(Task.id).limit(1))
    if task is None:
        return None
    claimed = db.execute(update(Task).where(Task.id == task.id, Task.status == "queued")
                         .values(status="running", started_at=now, attempts=Task.attempts + 1)).rowcount
    db.commit()
    if not claimed:
        return None
    db.refresh(task)
    handler = HANDLERS.get(task.type)
    try:
        if handler is None:
            raise ValueError(f"unknown task type {task.type}")
        result = handler(db, dict(task.payload or {}))
        db.commit()
        task = db.get(Task, task.id)
        task.status, task.result, task.finished_at, task.error = "done", result or {}, utcnow(), ""
    except Exception as e:
        log.exception("task %s (%s) failed", task.id, task.type)
        db.rollback()
        task = db.get(Task, task.id)
        task.error = f"{type(e).__name__}: {e}"[:2000]
        if task.type not in NEVER_RETRY and task.attempts < task.max_attempts:
            task.status, task.run_after = "queued", utcnow() + timedelta(seconds=60 * task.attempts)
        else:
            task.status, task.finished_at = "failed", utcnow()
            if (task.payload or {}).get("automatic") and task.type in ("prepare_application", "fill_form"):
                application = db.get(Application, task.payload.get("application_id"))
                if application is not None and application.status in ("draft", "prepared", "needs_manual"):
                    application.last_error = task.error
                    application.status = "needs_manual"
            emit(db, "task.failed", f"Background task “{task.type}” failed: {task.error[:200]}", level="error")
            from .core import notify
            notify(db, "task_failed", f"Automation run failed: {task.type}", task.error[:300], dedupe_key=f"taskfail:{task.id}")
    db.commit()
    return task


def _due(last_iso: Optional[str], interval: timedelta, now: datetime) -> bool:
    if not last_iso:
        return True
    try:
        last = datetime.fromisoformat(last_iso.rstrip("Z"))
    except ValueError:
        return True
    return now - last >= interval


def scheduler_tick(db: Session) -> list[str]:
    """Queue periodic work that is due. Schedules are editable from the dashboard."""
    cfg = get_setting(db, "schedule")
    runs = get_setting(db, "last_runs") or {}
    now = utcnow()
    queued = []
    last_search = runs.get("discovery") or {}
    if cfg.get("discovery_enabled") and _due(last_search.get("started_at") or last_search.get("at"), timedelta(hours=max(1, float(cfg["discovery_interval_hours"]))), now):
        if not db.scalar(select(Task.id).where(Task.type == "discovery", Task.status.in_(("queued", "running")))):
            enqueue(db, "discovery", {"trigger": "schedule"}, dedupe_key="discovery")
            queued.append("discovery")
    if cfg.get("verify_enabled") and _due((runs.get("verify") or {}).get("at"), timedelta(hours=max(1, float(cfg["verify_interval_hours"]))), now):
        enqueue(db, "verify_open", {}, dedupe_key="verify_open")
        queued.append("verify_open")
    from .models import EmailAccount
    if cfg.get("email_sync_enabled") and db.scalar(select(EmailAccount.id).limit(1)) and \
            _due((runs.get("email_sync") or {}).get("at"), timedelta(minutes=max(5, float(cfg["email_sync_interval_minutes"]))), now):
        enqueue(db, "email_sync", {}, dedupe_key="email_sync")
        queued.append("email_sync")
    db.commit()
    return queued


def housekeeping(db: Session) -> None:
    """Keep the database small: trim old finished tasks and very old events."""
    cutoff = utcnow() - timedelta(days=30)
    db.query(Task).filter(Task.status.in_(("done", "failed")), Task.finished_at < cutoff).delete(synchronize_session=False)
    db.query(Event).filter(Event.created_at < utcnow() - timedelta(days=180), Event.application_id.is_(None)).delete(synchronize_session=False)
    db.commit()


def main() -> None:  # pragma: no cover - process entry point
    logging.basicConfig(level=logging.INFO, format='{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}')
    stop = {"flag": False}

    def _stop(*_):
        stop["flag"] = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    with SessionLocal() as db:
        recover(db)
        emit(db, "worker.started", "Background worker started.")
        db.commit()
    last_tick = 0.0
    last_house = time.monotonic()
    while not stop["flag"]:
        with SessionLocal() as db:
            try:
                if time.monotonic() - last_tick > 60:
                    scheduler_tick(db)
                    last_tick = time.monotonic()
                if time.monotonic() - last_house > 6 * 3600:
                    housekeeping(db)
                    last_house = time.monotonic()
                task = run_one(db)
            except Exception:
                log.exception("worker loop error")
                task = None
        if task is None:
            for _ in range(6):
                if stop["flag"]:
                    break
                time.sleep(0.5)
    log.info("worker stopped")


if __name__ == "__main__":  # pragma: no cover
    main()
