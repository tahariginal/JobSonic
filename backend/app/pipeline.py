"""Pipeline state machine and the approval / submission safety rules.

The single most important invariant in the system lives here:
an application is only ever submitted when the *exact* content hash of the current
revision was explicitly approved, and each approval can drive at most one submission.
"""
from __future__ import annotations

import hashlib
import json
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from .core import audit, emit, enqueue, notify
from .db import utcnow
from .models import Application, ApprovalEvent, Document, Job, MaterialVersion

STAGES = ["discovered", "verified", "shortlisted", "preparing", "awaiting_approval", "submitted", "interview", "offer", "rejected"]
HIDDEN_STAGES = ["archived"]

# manual moves the user may make from the board; anything else needs the dedicated workflow
MANUAL_TRANSITIONS: dict[str, set[str]] = {
    "discovered": {"shortlisted", "archived"},
    "verified": {"shortlisted", "archived"},
    "shortlisted": {"verified", "preparing", "archived"},
    "preparing": {"shortlisted", "archived"},
    "awaiting_approval": {"preparing", "shortlisted", "archived"},
    "submitted": {"interview", "offer", "rejected"},
    "interview": {"offer", "rejected", "submitted"},
    "offer": {"interview", "rejected"},
    "rejected": {"submitted", "interview"},
    "archived": {"verified"},
}
# transitions that the UI must confirm explicitly
CONFIRM_REQUIRED = {("submitted", "rejected"), ("interview", "rejected"), ("offer", "rejected"), ("submitted", "offer"),
                    ("interview", "offer"), ("rejected", "submitted"), ("rejected", "interview"), ("offer", "interview"),
                    ("interview", "submitted"), ("awaiting_approval", "shortlisted"), ("awaiting_approval", "archived"),
                    ("preparing", "archived")}


class PipelineError(Exception):
    def __init__(self, message: str, code: str = "invalid"):
        super().__init__(message)
        self.code = code


def move_stage(db: Session, job: Job, to: str, *, confirm: bool = False, actor: str = "user") -> Job:
    frm = job.stage
    if to == frm:
        return job
    if to not in STAGES + HIDDEN_STAGES:
        raise PipelineError(f"Unknown stage “{to}”.")
    if to == "awaiting_approval":
        raise PipelineError("A job reaches Awaiting Approval only after its application form has been prepared.", "workflow")
    if to == "submitted" and frm not in ("interview", "rejected"):
        raise PipelineError("Use the approval inbox to submit, or “Mark as submitted manually” on the application.", "workflow")
    if to not in MANUAL_TRANSITIONS.get(frm, set()):
        raise PipelineError(f"Cannot move from {frm.replace('_', ' ')} to {to.replace('_', ' ')}.")
    if (frm, to) in CONFIRM_REQUIRED and not confirm:
        raise PipelineError("This transition needs confirmation.", "confirm_required")
    app = db.scalar(select(Application).where(Application.job_id == job.id))
    if frm == "awaiting_approval" and app is not None:
        # leaving the approval queue always voids any approval
        invalidate_approval(db, app, "moved out of approval queue")
        app.status = "prepared"
    job.stage = to
    emit(db, "pipeline.moved", f"{job.company.name} — {job.title}: {frm.replace('_', ' ')} → {to.replace('_', ' ')}.",
         job_id=job.id, application_id=app.id if app else None, data={"from": frm, "to": to, "actor": actor})
    audit(db, actor, "pipeline.move", f"job:{job.id}", {"from": frm, "to": to})
    return job


# ---------------------------------------------------------------- application content

def compute_content_hash(db: Session, app: Application) -> str:
    """Hash of exactly what would be submitted. Any change produces a different hash."""
    cv = db.get(Document, app.cv_document_id) if app.cv_document_id else None
    payload = {
        "job_id": app.job_id,
        "apply_url": app.job.apply_url,
        "cv_sha256": cv.sha256 if cv else "",
        "cover_letter": app.cover_letter or "",
        "answers": [
            {"key": a.get("key", ""), "label": a.get("label", ""), "value": a.get("value")}
            for a in sorted(app.answers or [], key=lambda a: a.get("key", ""))
        ],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def snapshot(db: Session, app: Application, reason: str) -> MaterialVersion:
    cv = db.get(Document, app.cv_document_id) if app.cv_document_id else None
    mv = MaterialVersion(
        application_id=app.id, revision=app.revision, content_hash=app.content_hash, reason=reason,
        snapshot={
            "cv": {"id": cv.id, "label": cv.label, "filename": cv.filename, "sha256": cv.sha256} if cv else None,
            "cover_letter": app.cover_letter, "fit_pitch": app.fit_pitch, "answers": app.answers,
            "materials_source": app.materials_source,
        },
    )
    db.add(mv)
    return mv


def invalidate_approval(db: Session, app: Application, why: str) -> None:
    if app.approved_revision is not None and app.status not in ("submitted", "submitting", "submit_uncertain"):
        db.add(ApprovalEvent(application_id=app.id, revision=app.approved_revision, content_hash=app.approved_hash,
                             action="invalidated", comment=why))
        app.approved_revision = None
        app.approved_hash = ""
        app.approved_at = None
        app.submit_key = ""


def touch_content(db: Session, app: Application, reason: str) -> bool:
    """Call after any edit. Bumps the revision and voids approval when the content really changed."""
    if app.status in ("submitted", "submitting", "submit_uncertain"):
        raise PipelineError("This application has already been sent and can no longer be edited.", "locked")
    new_hash = compute_content_hash(db, app)
    if new_hash == app.content_hash:
        return False
    had_approval = app.approved_revision is not None
    app.revision += 1
    app.content_hash = new_hash
    invalidate_approval(db, app, f"content changed: {reason}")
    snapshot(db, app, reason)
    if app.status in ("approved", "awaiting_approval", "failed", "form_filled", "needs_manual"):
        # the filled form no longer matches; it must be re-filled and re-approved
        app.status = "prepared"
        app.fill_report = {}
        if app.job.stage == "awaiting_approval":
            app.job.stage = "preparing"
    if had_approval:
        emit(db, "approval.invalidated", f"{app.job.company.name} — {app.job.title}: content changed, approval required again.",
             level="warn", job_id=app.job_id, application_id=app.id)
    return True


def blocking_issues(app: Application) -> list[dict]:
    return [i for i in (app.issues or []) if i.get("blocking")]


def approve(db: Session, app: Application, revision: int, content_hash: str, comment: str = "", actor: str = "user") -> Application:
    if app.status != "awaiting_approval":
        raise PipelineError(f"Application is “{app.status.replace('_', ' ')}”, not awaiting approval.", "state")
    current = compute_content_hash(db, app)
    if current != app.content_hash:
        touch_content(db, app, "drift detected at approval")
        raise PipelineError("The application changed since it was prepared. Review the new version.", "stale")
    if revision != app.revision or content_hash != app.content_hash:
        raise PipelineError("You reviewed an older version. Reload and review the current one.", "stale")
    if blocking_issues(app):
        raise PipelineError("Resolve the open issues before approving.", "issues")
    if not app.job.is_active:
        raise PipelineError("The vacancy is no longer listed.", "closed")
    app.approved_revision = app.revision
    app.approved_hash = app.content_hash
    app.approved_at = utcnow()
    app.submit_key = hashlib.sha256(f"{app.id}:{app.revision}:{app.content_hash}".encode()).hexdigest()
    app.status = "approved"
    app.last_error = ""
    db.add(ApprovalEvent(application_id=app.id, revision=app.revision, content_hash=app.content_hash, action="approve", comment=comment))
    emit(db, "approval.approved", f"Approved revision {app.revision}: {app.job.company.name} — {app.job.title}.",
         job_id=app.job_id, application_id=app.id)
    audit(db, actor, "application.approve", f"application:{app.id}", {"revision": app.revision, "hash": app.content_hash})
    enqueue(db, "submit_application", {"application_id": app.id, "submit_key": app.submit_key},
            dedupe_key=f"submit:{app.submit_key}")
    return app


def reject(db: Session, app: Application, comment: str = "", actor: str = "user") -> Application:
    if app.status in ("submitted", "submitting", "submit_uncertain"):
        raise PipelineError("Already sent.", "locked")
    db.add(ApprovalEvent(application_id=app.id, revision=app.revision, content_hash=app.content_hash, action="reject", comment=comment))
    invalidate_approval(db, app, "rejected by user")
    app.status = "declined"
    app.job.stage = "archived"
    emit(db, "approval.rejected", f"You declined to apply: {app.job.company.name} — {app.job.title}.", job_id=app.job_id, application_id=app.id)
    audit(db, actor, "application.reject", f"application:{app.id}", {"revision": app.revision})
    return app


def request_changes(db: Session, app: Application, comment: str, actor: str = "user") -> Application:
    if app.status in ("submitted", "submitting", "submit_uncertain"):
        raise PipelineError("Already sent.", "locked")
    db.add(ApprovalEvent(application_id=app.id, revision=app.revision, content_hash=app.content_hash, action="request_changes", comment=comment))
    invalidate_approval(db, app, "changes requested")
    app.status = "changes_requested"
    app.job.stage = "preparing"
    emit(db, "approval.changes_requested", f"Changes requested: {app.job.company.name} — {app.job.title}.", job_id=app.job_id, application_id=app.id)
    audit(db, actor, "application.request_changes", f"application:{app.id}", {"revision": app.revision, "comment": comment[:300]})
    return app


def begin_submit(db: Session, application_id: int, submit_key: str) -> Optional[Application]:
    """Claim the right to submit. Returns None when submission must not happen.

    All checks plus the state flip happen in one transaction; a second worker, a retry
    or a restarted task can never pass this gate for the same approval.
    """
    app = db.get(Application, application_id)
    if app is None:
        return None
    ok = (
        app.status == "approved"
        and app.submit_key
        and app.submit_key == submit_key
        and app.approved_revision == app.revision
        and app.approved_hash == app.content_hash
        and compute_content_hash(db, app) == app.approved_hash
        and app.submitted_at is None
        and app.submit_started_at is None
    )
    if not ok:
        emit(db, "submit.blocked", f"Submission blocked for {app.job.company.name} — {app.job.title}: approval is not valid for the current version.",
             level="warn", job_id=app.job_id, application_id=app.id)
        db.commit()
        return None
    app.status = "submitting"
    app.submit_started_at = utcnow()
    db.commit()
    return app


def finish_submit(db: Session, app: Application, outcome: str, *, confirmation: Optional[dict] = None, error: str = "") -> None:
    """outcome: submitted | failed_before_send | uncertain"""
    name = f"{app.job.company.name} — {app.job.title}"
    if outcome == "submitted":
        app.status = "submitted"
        app.submitted_at = utcnow()
        app.submitted_via = "agent"
        app.confirmation = confirmation or {}
        app.job.stage = "submitted"
        emit(db, "submit.succeeded", f"Application submitted: {name}.", job_id=app.job_id, application_id=app.id)
        notify(db, "submitted", f"Submitted: {app.job.title}", app.job.company.name, dedupe_key=f"submitted:{app.id}",
               job_id=app.job_id, application_id=app.id)
    elif outcome == "failed_before_send":
        # nothing was sent: the approval is consumed, the user must look and approve again
        app.status = "failed"
        app.last_error = error[:2000]
        app.submit_started_at = None
        invalidate_approval(db, app, "submission failed before sending")
        app.status = "failed"
        emit(db, "submit.failed", f"Submission failed before sending: {name}. {error[:200]}", level="error", job_id=app.job_id, application_id=app.id)
        notify(db, "submit_failed", f"Submission failed: {app.job.title}", error[:300], dedupe_key=f"submitfail:{app.id}:{app.revision}:{utcnow().isoformat()}",
               job_id=app.job_id, application_id=app.id)
    else:
        app.status = "submit_uncertain"
        app.last_error = error[:2000]
        app.confirmation = confirmation or {}
        emit(db, "submit.uncertain", f"Submission outcome unknown for {name}. It will NOT be retried automatically — check your email and confirm manually.",
             level="error", job_id=app.job_id, application_id=app.id)
        notify(db, "submit_uncertain", f"Check manually: {app.job.title}",
               "The submit button was pressed but no confirmation was detected. Verify before doing anything else.",
               dedupe_key=f"uncertain:{app.id}", job_id=app.job_id, application_id=app.id)
    db.commit()


def recover_interrupted(db: Session) -> int:
    """After a crash/restart: anything caught mid-submit becomes 'uncertain' and is never auto-retried."""
    n = 0
    for app in db.scalars(select(Application).where(Application.status == "submitting")):
        finish_submit(db, app, "uncertain", error="The service restarted while this application was being submitted.")
        n += 1
    return n


def mark_submitted_manually(db: Session, app: Application, note: str = "", actor: str = "user") -> Application:
    if app.status == "submitted":
        raise PipelineError("Already marked as submitted.", "locked")
    app.status = "submitted"
    app.submitted_at = utcnow()
    app.submitted_via = "manual"
    app.confirmation = {"note": note, "manual": True}
    app.job.stage = "submitted"
    emit(db, "submit.manual", f"Marked as submitted manually: {app.job.company.name} — {app.job.title}.", job_id=app.job_id, application_id=app.id)
    audit(db, actor, "application.mark_submitted", f"application:{app.id}", {"note": note[:300]})
    return app
