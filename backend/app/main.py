"""SONIC JOBS HTTP API + static dashboard hosting."""
from __future__ import annotations

import hashlib
import logging
import re
import secrets
from collections import Counter, defaultdict
from datetime import timedelta
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from . import ai, emailing, pipeline, preparation
from .config import get_settings
from .core import DEFAULT_SETTINGS, audit, emit, enqueue, get_setting, iso, set_setting
from .db import get_db, utcnow
from .discovery import VISA_LABEL, load_profile
from .models import (
    AIUsage,
    Application,
    ApprovalEvent,
    AuditLog,
    AuthSession,
    Company,
    Document,
    EmailAccount,
    EmailMessage,
    Event,
    Job,
    MaterialVersion,
    Note,
    Notification,
    Profile,
    Screenshot,
    Task,
    User,
)
from .schemas import ProfileData, profile_gaps
from .security import SESSION_COOKIE, client_ip, create_session, limiter, lookup_session, require_session, verify_password
from .sources import ADAPTERS, PoliteClient, SourceError

log = logging.getLogger("sonic.api")
settings = get_settings()

app = FastAPI(title="SONIC JOBS", docs_url=None, redoc_url=None, openapi_url=None)
public = APIRouter(prefix="/api")
api = APIRouter(prefix="/api", dependencies=[Depends(require_session)])

CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
       "font-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    if request.headers.get("content-length") and int(request.headers["content-length"]) > 8 * 1024 * 1024:
        return JSONResponse({"detail": "Request too large"}, status_code=413)
    response: Response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = CSP
    if settings.cookie_secure:
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    if request.url.path.startswith("/api"):
        response.headers["Cache-Control"] = "no-store"
    return response


def _actor(request: Request) -> str:
    return "user"


# =============================================================== auth

class LoginIn(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=256)


@public.post("/auth/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    ip = client_ip(request)
    if not limiter.check(f"login:{ip}", 6, 300):
        audit(db, "anonymous", "auth.rate_limited", ip=ip)
        db.commit()
        raise HTTPException(429, "Too many attempts. Try again in a few minutes.")
    user = db.scalar(select(User).where(User.username == body.username))
    # verify against a dummy hash when the user is unknown so timing does not reveal usernames
    ok = verify_password(user.password_hash if user else "$argon2id$v=19$m=65536,t=3,p=4$c29tZXNhbHRzb21lc2FsdA$0000000000000000000000000000000000000000000", body.password)
    if not user or not ok:
        audit(db, body.username[:64], "auth.login_failed", ip=ip)
        db.commit()
        raise HTTPException(401, "Invalid username or password")
    token, sess = create_session(db, user, request.headers.get("user-agent", ""))
    audit(db, user.username, "auth.login", ip=ip)
    db.commit()
    response.set_cookie(SESSION_COOKIE, token, httponly=True, secure=settings.cookie_secure, samesite="lax",
                        max_age=settings.session_hours * 3600, path="/")
    return {"username": user.username, "csrf_token": sess.csrf_token}


@public.get("/auth/me")
def me(request: Request, db: Session = Depends(get_db)):
    s = lookup_session(db, request.cookies.get(SESSION_COOKIE))
    if s is None:
        raise HTTPException(401, "Not authenticated")
    user = db.get(User, s.user_id)
    return {"username": user.username, "csrf_token": s.csrf_token}


@api.post("/auth/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    db.delete(db.get(AuthSession, request.state.session.id))
    db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@public.get("/health")
def health(db: Session = Depends(get_db)):
    """Unauthenticated liveness probe: deliberately reveals nothing about the data."""
    try:
        db.execute(select(func.count(User.id))).scalar()
        hb = db.scalar(select(Event.created_at).where(Event.type.like("worker.%")).order_by(Event.id.desc()).limit(1))
        return {"status": "ok", "db": "ok", "time": iso(utcnow())}
    except Exception:
        return JSONResponse({"status": "error", "db": "unavailable"}, status_code=503)


# =============================================================== profile & documents

@api.get("/profile")
def get_profile(db: Session = Depends(get_db)):
    p = load_profile(db)
    db.commit()
    row = db.get(Profile, 1)
    return {"data": p.model_dump(), "gaps": profile_gaps(p), "updated_at": iso(row.updated_at) if row else None}


@api.put("/profile")
def put_profile(body: ProfileData, request: Request, db: Session = Depends(get_db)):
    row = db.get(Profile, 1)
    if row is None:
        row = Profile(id=1, data={})
        db.add(row)
    row.data = body.model_dump()
    row.updated_at = utcnow()
    audit(db, _actor(request), "profile.update", ip=client_ip(request))
    emit(db, "profile.updated", "Candidate profile updated; jobs will be re-scored.")
    enqueue(db, "reanalyze", {}, dedupe_key="reanalyze")
    db.commit()
    return {"data": body.model_dump(), "gaps": profile_gaps(body)}


ALLOWED_DOCS = {".pdf": (b"%PDF", "application/pdf"),
                ".docx": (b"PK", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
                ".txt": (b"", "text/plain")}
MAX_DOC = 5 * 1024 * 1024


def _doc_json(d: Document) -> dict:
    return {"id": d.id, "kind": d.kind, "label": d.label, "tags": d.tags or [], "filename": d.filename, "size": d.size,
            "is_default": d.is_default, "created_at": iso(d.created_at), "sha256": d.sha256[:12]}


@api.get("/documents")
def list_documents(db: Session = Depends(get_db)):
    return [_doc_json(d) for d in db.scalars(select(Document).order_by(Document.created_at.desc()))]


@api.post("/documents")
async def upload_document(request: Request, file: UploadFile = File(...), kind: str = Form("cv"), label: str = Form(""),
                          tags: str = Form(""), db: Session = Depends(get_db)):
    if kind not in ("cv", "cover_letter", "other"):
        raise HTTPException(400, "Invalid document kind")
    name = Path(file.filename or "document").name
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED_DOCS:
        raise HTTPException(400, "Only PDF, DOCX or TXT files are accepted")
    data = await file.read(MAX_DOC + 1)
    if len(data) > MAX_DOC:
        raise HTTPException(413, "File is larger than 5 MB")
    magic, mime = ALLOWED_DOCS[ext]
    if not data or not data.startswith(magic):
        raise HTTPException(400, "File content does not match its extension")
    stored = secrets.token_hex(16) + ext
    path = settings.uploads_dir / stored
    path.write_bytes(data)
    path.chmod(0o600)
    safe_name = re.sub(r"[^\w.\- ]", "_", name)[:200]
    first = db.scalar(select(func.count(Document.id)).where(Document.kind == kind)) == 0
    d = Document(kind=kind, label=(label or safe_name)[:160], tags=[t.strip().lower() for t in tags.split(",") if t.strip()][:8],
                 filename=safe_name, stored_name=stored, mime=mime, size=len(data), sha256=hashlib.sha256(data).hexdigest(), is_default=first)
    db.add(d)
    audit(db, _actor(request), "document.upload", detail={"filename": safe_name, "kind": kind}, ip=client_ip(request))
    db.commit()
    return _doc_json(d)


class DocPatch(BaseModel):
    label: Optional[str] = Field(None, max_length=160)
    tags: Optional[list[str]] = None
    is_default: Optional[bool] = None


@api.patch("/documents/{doc_id}")
def patch_document(doc_id: int, body: DocPatch, db: Session = Depends(get_db)):
    d = db.get(Document, doc_id)
    if d is None:
        raise HTTPException(404)
    if body.label is not None:
        d.label = body.label
    if body.tags is not None:
        d.tags = [t.strip().lower()[:30] for t in body.tags if t.strip()][:8]
    if body.is_default:
        for other in db.scalars(select(Document).where(Document.kind == d.kind)):
            other.is_default = other.id == d.id
    db.commit()
    return _doc_json(d)


@api.delete("/documents/{doc_id}")
def delete_document(doc_id: int, request: Request, db: Session = Depends(get_db)):
    d = db.get(Document, doc_id)
    if d is None:
        raise HTTPException(404)
    in_use = db.scalar(select(func.count(Application.id)).where(Application.cv_document_id == d.id,
                                                                Application.status.in_(("submitted", "submitting", "approved", "submit_uncertain"))))
    if in_use:
        raise HTTPException(409, "This document was used in a submitted or approved application and is kept for the record.")
    for a in db.scalars(select(Application).where(Application.cv_document_id == d.id)):
        a.cv_document_id = None
        try:
            pipeline.touch_content(db, a, "CV removed")
        except pipeline.PipelineError:
            pass
    (settings.uploads_dir / d.stored_name).unlink(missing_ok=True)
    db.delete(d)
    audit(db, _actor(request), "document.delete", detail={"filename": d.filename}, ip=client_ip(request))
    db.commit()
    return {"ok": True}


@api.get("/documents/{doc_id}/download")
def download_document(doc_id: int, db: Session = Depends(get_db)):
    d = db.get(Document, doc_id)
    if d is None:
        raise HTTPException(404)
    path = settings.uploads_dir / d.stored_name
    if not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, media_type=d.mime, filename=d.filename)


# =============================================================== jobs

def _is_new(j: Job, now) -> bool:
    return (not j.seen) and (now - j.discovered_at) < timedelta(days=7)


def _job_row(j: Job, now) -> dict:
    return {
        "id": j.id, "company": j.company.name, "provider": j.provider, "title": j.title, "summary": j.summary,
        "fit_stars": j.fit_stars, "fit_score": j.fit_score, "fit_reason": j.fit_reason, "analysis_source": j.analysis_source,
        "salary_text": j.salary_text, "location": j.location_raw, "country": j.country, "region": j.region,
        "remote_mode": j.remote_mode, "remote_scope": j.remote_scope, "visa_status": j.visa_status,
        "visa_label": VISA_LABEL.get(j.visa_status, j.visa_status), "relocation": j.relocation,
        "apply_url": j.apply_url, "eligibility": j.eligibility, "experience_level": j.experience_level, "min_years": j.min_years,
        "stage": j.stage, "saved": j.saved, "is_active": j.is_active, "is_new": _is_new(j, now),
        "is_updated": bool(j.updated_content_at and not j.seen and j.updated_content_at > j.discovered_at),
        "discovered_at": iso(j.discovered_at), "posted_at": iso(j.posted_at), "role_family": j.role_family,
        "rejection_reasons": [r["text"] for r in (j.eligibility_reasons or []) if r.get("severity") == "reject"][:3],
        "review_reasons": [r["text"] for r in (j.eligibility_reasons or []) if r.get("severity") == "review"][:3],
    }


def _job_query(q: str = "", country: str = "", region: str = "", visa: str = "", eligibility: str = "", level: str = "",
               min_stars: int = 0, stage: str = "", saved: Optional[bool] = None, active: Optional[bool] = True,
               new_only: bool = False, family: str = "", remote: str = "", days: int = 0):
    stmt = select(Job).join(Company, Job.company_id == Company.id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Job.title.ilike(like), Company.name.ilike(like), Job.location_raw.ilike(like), Job.summary.ilike(like)))
    if country:
        stmt = stmt.where(Job.country.in_(country.split("|")))
    if region:
        stmt = stmt.where(Job.region.in_(region.split("|")))
    if visa:
        stmt = stmt.where(Job.visa_status.in_(visa.split("|")))
    if eligibility:
        stmt = stmt.where(Job.eligibility.in_(eligibility.split("|")))
    if level:
        stmt = stmt.where(Job.experience_level.in_(level.split("|")))
    if family:
        stmt = stmt.where(Job.role_family.in_(family.split("|")))
    if remote:
        stmt = stmt.where(Job.remote_mode.in_(remote.split("|")))
    if min_stars:
        stmt = stmt.where(Job.fit_stars >= min_stars)
    if stage:
        stmt = stmt.where(Job.stage.in_(stage.split("|")))
    else:
        stmt = stmt.where(Job.stage != "archived")
    if saved is not None:
        stmt = stmt.where(Job.saved.is_(saved))
    if active is not None:
        stmt = stmt.where(Job.is_active.is_(active))
    if new_only:
        stmt = stmt.where(Job.seen.is_(False), Job.discovered_at >= utcnow() - timedelta(days=7))
    if days:
        stmt = stmt.where(Job.discovered_at >= utcnow() - timedelta(days=days))
    return stmt


SORTS = {
    "fit": (Job.fit_score.desc(), Job.discovered_at.desc()),
    "newest": (Job.discovered_at.desc(), Job.id.desc()),
    "oldest": (Job.discovered_at.asc(),),
    "company": (Company.name.asc(), Job.title.asc()),
    "salary": (Job.salary_max.desc().nulls_last(), Job.fit_score.desc()),
    "title": (Job.title.asc(),),
}


@api.get("/jobs")
def list_jobs(q: str = "", country: str = "", region: str = "", visa: str = "", eligibility: str = "", level: str = "",
              min_stars: int = Query(0, ge=0, le=5), stage: str = "", saved: Optional[bool] = None, active: Optional[bool] = True,
              new_only: bool = False, family: str = "", remote: str = "", days: int = Query(0, ge=0, le=365),
              sort: str = "fit", page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200), db: Session = Depends(get_db)):
    stmt = _job_query(q, country, region, visa, eligibility, level, min_stars, stage, saved, active, new_only, family, remote, days)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(*SORTS.get(sort, SORTS["fit"])).offset((page - 1) * page_size).limit(page_size)).all()
    now = utcnow()
    return {"total": total, "page": page, "page_size": page_size, "items": [_job_row(j, now) for j in rows]}


@api.get("/jobs/facets")
def job_facets(db: Session = Depends(get_db)):
    base = select(Job).where(Job.is_active.is_(True), Job.stage != "archived").subquery()

    def counts(col):
        return [{"value": v, "count": c} for v, c in db.execute(select(col, func.count()).group_by(col).order_by(func.count().desc())).all()]

    return {"country": counts(base.c.country), "region": counts(base.c.region), "visa_status": counts(base.c.visa_status),
            "eligibility": counts(base.c.eligibility), "experience_level": counts(base.c.experience_level),
            "role_family": counts(base.c.role_family), "remote_mode": counts(base.c.remote_mode), "fit_stars": counts(base.c.fit_stars)}


def _app_summary(a: Optional[Application]) -> Optional[dict]:
    if a is None:
        return None
    return {"id": a.id, "status": a.status, "revision": a.revision, "updated_at": iso(a.updated_at), "submitted_at": iso(a.submitted_at)}


@api.get("/jobs/{job_id}")
def job_detail(job_id: int, db: Session = Depends(get_db)):
    j = db.get(Job, job_id)
    if j is None:
        raise HTTPException(404)
    now = utcnow()
    out = _job_row(j, now)
    a = db.scalar(select(Application).where(Application.job_id == j.id))
    out.update({
        "description": j.description_text, "department": j.department, "employment_type": j.employment_type,
        "canonical_url": j.canonical_url, "source_url": j.source_url, "external_id": j.external_id,
        "board_token": j.company.board_token, "salary_min": j.salary_min, "salary_max": j.salary_max, "salary_currency": j.salary_currency,
        "eligibility_reasons": j.eligibility_reasons or [], "visa_evidence": j.visa_evidence or [], "visa_checked_at": iso(j.visa_checked_at),
        "relocation_evidence": j.relocation_evidence or [], "remote_from_morocco": j.remote_from_morocco,
        "fit_breakdown": j.fit_breakdown or {}, "ai_notes": j.ai_notes, "manual_override": j.manual_override,
        "last_verified_at": iso(j.last_verified_at), "last_seen_at": iso(j.last_seen_at), "closed_at": iso(j.closed_at),
        "updated_content_at": iso(j.updated_content_at), "fingerprint": j.fingerprint[:16],
        "application": _app_summary(a),
        "notes": [{"id": n.id, "text": n.text, "created_at": iso(n.created_at)} for n in db.scalars(select(Note).where(Note.job_id == j.id).order_by(Note.id.desc()))],
        "allowed_moves": sorted(pipeline.MANUAL_TRANSITIONS.get(j.stage, set())),
    })
    if not j.seen:
        j.seen = True
        db.commit()
    return out


class JobPatch(BaseModel):
    saved: Optional[bool] = None
    seen: Optional[bool] = None
    eligibility: Optional[str] = Field(None, pattern="^(eligible|needs_review|rejected|auto)$")


@api.patch("/jobs/{job_id}")
def patch_job(job_id: int, body: JobPatch, request: Request, db: Session = Depends(get_db)):
    j = db.get(Job, job_id)
    if j is None:
        raise HTTPException(404)
    if body.saved is not None:
        j.saved = body.saved
    if body.seen is not None:
        j.seen = body.seen
    if body.eligibility is not None:
        if body.eligibility == "auto":
            j.manual_override = False
            from .discovery import apply_analysis
            apply_analysis(j, load_profile(db))
        else:
            j.manual_override = True
            j.eligibility = body.eligibility
        audit(db, _actor(request), "job.eligibility_override", f"job:{j.id}", {"to": body.eligibility})
        emit(db, "job.override", f"You set {j.company.name} — {j.title} to “{body.eligibility.replace('_', ' ')}”.", job_id=j.id)
    db.commit()
    return _job_row(j, utcnow())


class StageIn(BaseModel):
    to: str
    confirm: bool = False


@api.post("/jobs/{job_id}/stage")
def set_stage(job_id: int, body: StageIn, request: Request, db: Session = Depends(get_db)):
    j = db.get(Job, job_id)
    if j is None:
        raise HTTPException(404)
    try:
        pipeline.move_stage(db, j, body.to, confirm=body.confirm, actor=_actor(request))
    except pipeline.PipelineError as e:
        db.rollback()
        raise HTTPException(409, {"message": str(e), "code": e.code})
    if body.to == "preparing":
        enqueue(db, "prepare_application", {"job_id": j.id}, dedupe_key=f"prepare:{j.id}")
    db.commit()
    return {"id": j.id, "stage": j.stage, "allowed_moves": sorted(pipeline.MANUAL_TRANSITIONS.get(j.stage, set()))}


@api.post("/jobs/{job_id}/verify")
def verify_now(job_id: int, db: Session = Depends(get_db)):
    from .discovery import verify_job
    j = db.get(Job, job_id)
    if j is None:
        raise HTTPException(404)
    live = verify_job(db, j)
    db.commit()
    return {"live": live, "is_active": j.is_active, "last_verified_at": iso(j.last_verified_at)}


class NoteIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


@api.post("/jobs/{job_id}/notes")
def add_note(job_id: int, body: NoteIn, db: Session = Depends(get_db)):
    if db.get(Job, job_id) is None:
        raise HTTPException(404)
    n = Note(job_id=job_id, text=body.text)
    db.add(n)
    db.commit()
    return {"id": n.id, "text": n.text, "created_at": iso(n.created_at)}


@api.delete("/notes/{note_id}")
def delete_note(note_id: int, db: Session = Depends(get_db)):
    n = db.get(Note, note_id)
    if n:
        db.delete(n)
        db.commit()
    return {"ok": True}


@api.post("/jobs/{job_id}/ai-evaluate")
def ai_evaluate(job_id: int, db: Session = Depends(get_db)):
    j = db.get(Job, job_id)
    if j is None:
        raise HTTPException(404)
    st = ai.status(db)
    if not st["available"]:
        raise HTTPException(409, {"message": st["reason"], "code": "ai_unavailable"})
    t = enqueue(db, "ai_evaluate", {"job_id": j.id}, dedupe_key=f"ai:{j.id}")
    db.commit()
    return {"task_id": t.id}


@api.post("/jobs/{job_id}/prepare")
def prepare(job_id: int, db: Session = Depends(get_db)):
    j = db.get(Job, job_id)
    if j is None:
        raise HTTPException(404)
    if not j.is_active:
        raise HTTPException(409, {"message": "This vacancy is closed.", "code": "closed"})
    if j.eligibility == "rejected" and not j.manual_override:
        raise HTTPException(409, {"message": "This job failed a hard eligibility rule. Override its eligibility first if you still want to apply.", "code": "ineligible"})
    if j.stage in ("discovered", "verified"):
        j.stage = "shortlisted"
    t = enqueue(db, "prepare_application", {"job_id": j.id}, dedupe_key=f"prepare:{j.id}")
    db.commit()
    return {"task_id": t.id}


# =============================================================== pipeline board

@api.get("/pipeline")
def pipeline_board(db: Session = Depends(get_db)):
    now = utcnow()
    cols = {s: [] for s in pipeline.STAGES}
    counts = dict(db.execute(select(Job.stage, func.count()).group_by(Job.stage)).all())
    apps = {a.job_id: a for a in db.scalars(select(Application))}
    for stage in pipeline.STAGES:
        stmt = select(Job).where(Job.stage == stage)
        if stage in ("discovered", "verified"):
            # the first columns can hold thousands of rows: show the best active candidates only
            stmt = stmt.where(Job.is_active.is_(True), Job.eligibility != "rejected").order_by(Job.fit_score.desc()).limit(25)
        else:
            stmt = stmt.order_by(Job.fit_score.desc()).limit(200)
        for j in db.scalars(stmt):
            a = apps.get(j.id)
            cols[stage].append({
                "id": j.id, "company": j.company.name, "title": j.title, "fit_stars": j.fit_stars, "location": j.location_raw,
                "country": j.country, "visa_status": j.visa_status, "eligibility": j.eligibility, "is_active": j.is_active,
                "is_new": _is_new(j, now), "application": _app_summary(a),
                "allowed_moves": sorted(pipeline.MANUAL_TRANSITIONS.get(j.stage, set())),
            })
    # early columns count what they show: open jobs that passed the hard filters
    for stage in ("discovered", "verified"):
        counts[stage] = db.scalar(select(func.count(Job.id)).where(Job.stage == stage, Job.is_active.is_(True), Job.eligibility != "rejected")) or 0
    return {"stages": pipeline.STAGES, "columns": cols, "counts": {s: counts.get(s, 0) for s in pipeline.STAGES},
            "confirm_required": [list(x) for x in pipeline.CONFIRM_REQUIRED]}


# =============================================================== applications & approvals

def _app_json(db: Session, a: Application, full: bool = True) -> dict:
    j = a.job
    cv = db.get(Document, a.cv_document_id) if a.cv_document_id else None
    out = {
        "id": a.id, "job_id": j.id, "company": j.company.name, "title": j.title, "location": j.location_raw, "country": j.country,
        "apply_url": j.apply_url, "form_url": (a.form_schema or {}).get("form_url") or j.apply_url, "provider": j.provider,
        "status": a.status, "stage": j.stage, "revision": a.revision, "content_hash": a.content_hash,
        "fit_stars": j.fit_stars, "fit_reason": j.fit_reason, "visa_status": j.visa_status, "is_active": j.is_active,
        "cv": _doc_json(cv) if cv else None, "issues": a.issues or [], "blocking_issues": len(pipeline.blocking_issues(a)),
        "approved_revision": a.approved_revision, "approved_at": iso(a.approved_at), "submitted_at": iso(a.submitted_at),
        "submitted_via": a.submitted_via, "last_error": a.last_error, "materials_source": a.materials_source,
        "created_at": iso(a.created_at), "updated_at": iso(a.updated_at),
    }
    if not full:
        return out
    shots = list(db.scalars(select(Screenshot).where(Screenshot.application_id == a.id).order_by(Screenshot.id.desc())))
    rep = a.fill_report or {}
    out.update({
        "cover_letter": a.cover_letter, "fit_pitch": a.fit_pitch, "answers": a.answers or [],
        "form_source": (a.form_schema or {}).get("source", ""),
        "fill_report": {k: rep.get(k) for k in ("mode", "outcome", "ok", "filled", "unfilled", "unmapped_required", "blockers", "error",
                                               "started_at", "finished_at", "final_url", "revision", "needs_manual", "closed")} if rep else None,
        "fill_is_current": bool(rep) and rep.get("revision") == a.revision and rep.get("content_hash") == a.content_hash,
        "confirmation": a.confirmation or {},
        "screenshots": [{"id": s.id, "kind": s.kind, "revision": s.revision, "created_at": iso(s.created_at)} for s in shots],
        "approvals": [{"action": e.action, "revision": e.revision, "comment": e.comment, "created_at": iso(e.created_at), "hash": e.content_hash[:10]}
                      for e in db.scalars(select(ApprovalEvent).where(ApprovalEvent.application_id == a.id).order_by(ApprovalEvent.id.desc()))],
        "versions": [{"revision": v.revision, "reason": v.reason, "created_at": iso(v.created_at), "hash": v.content_hash[:10]}
                     for v in db.scalars(select(MaterialVersion).where(MaterialVersion.application_id == a.id).order_by(MaterialVersion.id.desc()))],
        "emails": [_email_json(m) for m in db.scalars(select(EmailMessage).where(EmailMessage.application_id == a.id).order_by(EmailMessage.received_at.desc()))],
        "timeline": [{"id": e.id, "type": e.type, "message": e.message, "level": e.level, "created_at": iso(e.created_at)}
                     for e in db.scalars(select(Event).where(or_(Event.application_id == a.id, Event.job_id == j.id)).order_by(Event.id.desc()).limit(80))],
        "notes": [{"id": n.id, "text": n.text, "created_at": iso(n.created_at)} for n in db.scalars(select(Note).where(Note.job_id == j.id).order_by(Note.id.desc()))],
        "job": {"description": j.description_text, "summary": j.summary, "visa_evidence": j.visa_evidence or [], "eligibility": j.eligibility,
                "eligibility_reasons": j.eligibility_reasons or [], "salary_text": j.salary_text, "remote_mode": j.remote_mode,
                "visa_label": VISA_LABEL.get(j.visa_status, j.visa_status), "canonical_url": j.canonical_url, "last_verified_at": iso(j.last_verified_at)},
    })
    return out


def _get_app(db: Session, app_id: int) -> Application:
    a = db.get(Application, app_id)
    if a is None:
        raise HTTPException(404)
    return a


@api.get("/applications")
def list_applications(status: str = "", db: Session = Depends(get_db)):
    stmt = select(Application).order_by(Application.updated_at.desc())
    if status:
        stmt = stmt.where(Application.status.in_(status.split("|")))
    return [_app_json(db, a, full=False) for a in db.scalars(stmt.limit(300))]


@api.get("/approvals")
def approvals(db: Session = Depends(get_db)):
    waiting = db.scalars(select(Application).where(Application.status == "awaiting_approval").order_by(Application.updated_at.desc())).all()
    attention = db.scalars(select(Application).where(Application.status.in_(("needs_manual", "failed", "submit_uncertain", "changes_requested", "prepared")))
                           .order_by(Application.updated_at.desc())).all()
    return {"awaiting": [_app_json(db, a, full=False) for a in waiting], "attention": [_app_json(db, a, full=False) for a in attention]}


@api.get("/applications/{app_id}")
def application_detail(app_id: int, db: Session = Depends(get_db)):
    return _app_json(db, _get_app(db, app_id))


class AnswerEdit(BaseModel):
    key: str
    value: Any = None


class AppEdit(BaseModel):
    cover_letter: Optional[str] = Field(None, max_length=8000)
    cv_document_id: Optional[int] = None
    answers: Optional[list[AnswerEdit]] = None


@api.put("/applications/{app_id}")
def edit_application(app_id: int, body: AppEdit, request: Request, db: Session = Depends(get_db)):
    a = _get_app(db, app_id)
    if a.status in ("submitted", "submitting", "submit_uncertain"):
        raise HTTPException(409, {"message": "This application has already been sent.", "code": "locked"})
    if body.cv_document_id is not None:
        d = db.get(Document, body.cv_document_id)
        if d is None or d.kind != "cv":
            raise HTTPException(400, "Unknown CV document")
        a.cv_document_id = d.id
    answers = [dict(x) for x in (a.answers or [])]
    if body.cover_letter is not None and body.cover_letter != a.cover_letter:
        a.cover_letter = body.cover_letter
        a.materials_source = "edited"
        for x in answers:
            if x.get("kind") == "cover_letter" and x.get("type") != "file":
                x["value"], x["source"] = body.cover_letter, "manual"
    if body.answers:
        by_key = {x["key"]: x for x in answers}
        for e in body.answers:
            x = by_key.get(e.key)
            if x is None or x.get("type") in ("file", "info"):
                continue
            v = e.value
            if isinstance(v, str):
                v = v.strip()[:6000]
                if x.get("options") and v and v not in x["options"]:
                    raise HTTPException(400, f"“{v}” is not one of the options for “{x.get('label')}”")
            if v != x.get("value"):
                x["value"], x["source"], x["note"] = (v if v not in ("",) else None), "manual", ""
                if x.get("kind") == "cover_letter" and isinstance(v, str):
                    a.cover_letter = v
    a.answers = answers
    cv = db.get(Document, a.cv_document_id) if a.cv_document_id else None
    for x in a.answers:
        if x.get("kind") == "resume":
            x["value"] = {"document_id": cv.id, "filename": cv.filename} if cv else None
    a.answers = list(a.answers)
    a.issues = preparation.collect_issues(a, load_profile(db), cv)
    try:
        changed = pipeline.touch_content(db, a, "edited by you")
    except pipeline.PipelineError as e:
        db.rollback()
        raise HTTPException(409, {"message": str(e), "code": e.code})
    audit(db, _actor(request), "application.edit", f"application:{a.id}", {"revision": a.revision, "changed": changed}, ip=client_ip(request))
    db.commit()
    return _app_json(db, a)


@api.post("/applications/{app_id}/fill")
def fill(app_id: int, db: Session = Depends(get_db)):
    a = _get_app(db, app_id)
    if a.status in ("submitted", "submitting", "submit_uncertain", "approved"):
        raise HTTPException(409, {"message": f"Application is {a.status.replace('_', ' ')}.", "code": "state"})
    if pipeline.blocking_issues(a):
        raise HTTPException(409, {"message": "Resolve the open issues first.", "code": "issues"})
    t = enqueue(db, "fill_form", {"application_id": a.id}, dedupe_key=f"fill:{a.id}")
    db.commit()
    return {"task_id": t.id}


class ApproveIn(BaseModel):
    revision: int
    content_hash: str = Field(min_length=64, max_length=64)
    comment: str = Field("", max_length=1000)


class CommentIn(BaseModel):
    comment: str = Field("", max_length=2000)


def _pipeline_call(db: Session, fn, *args, **kw):
    try:
        out = fn(db, *args, **kw)
        db.commit()
        return out
    except pipeline.PipelineError as e:
        db.commit()  # keep any invalidation that happened before the error
        raise HTTPException(409, {"message": str(e), "code": e.code})


@api.post("/applications/{app_id}/approve")
def approve(app_id: int, body: ApproveIn, request: Request, db: Session = Depends(get_db)):
    a = _get_app(db, app_id)
    _pipeline_call(db, pipeline.approve, a, body.revision, body.content_hash, body.comment, actor=_actor(request))
    return _app_json(db, a)


@api.post("/applications/{app_id}/reject")
def reject(app_id: int, body: CommentIn, request: Request, db: Session = Depends(get_db)):
    a = _get_app(db, app_id)
    _pipeline_call(db, pipeline.reject, a, body.comment, actor=_actor(request))
    return _app_json(db, a)


@api.post("/applications/{app_id}/request-changes")
def request_changes(app_id: int, body: CommentIn, request: Request, db: Session = Depends(get_db)):
    a = _get_app(db, app_id)
    _pipeline_call(db, pipeline.request_changes, a, body.comment, actor=_actor(request))
    return _app_json(db, a)


@api.post("/applications/{app_id}/mark-submitted")
def mark_submitted(app_id: int, body: CommentIn, request: Request, db: Session = Depends(get_db)):
    a = _get_app(db, app_id)
    _pipeline_call(db, pipeline.mark_submitted_manually, a, body.comment, actor=_actor(request))
    return _app_json(db, a)


@api.post("/applications/{app_id}/mark-not-sent")
def mark_not_sent(app_id: int, body: CommentIn, request: Request, db: Session = Depends(get_db)):
    """After an uncertain submission the user checked and confirmed nothing was sent."""
    a = _get_app(db, app_id)
    if a.status != "submit_uncertain":
        raise HTTPException(409, {"message": "Only applies to an uncertain submission.", "code": "state"})
    a.status, a.submit_started_at, a.submit_key = "prepared", None, ""
    a.approved_revision, a.approved_hash, a.approved_at = None, "", None
    a.job.stage = "preparing"
    db.add(ApprovalEvent(application_id=a.id, revision=a.revision, content_hash=a.content_hash, action="invalidated",
                         comment="You confirmed the uncertain submission was not sent. " + body.comment))
    emit(db, "submit.cleared", f"You confirmed nothing was sent: {a.job.company.name} — {a.job.title}. A new approval is required.",
         job_id=a.job_id, application_id=a.id)
    audit(db, _actor(request), "application.mark_not_sent", f"application:{a.id}")
    db.commit()
    return _app_json(db, a)


@api.get("/screenshots/{shot_id}")
def screenshot(shot_id: int, db: Session = Depends(get_db)):
    s = db.get(Screenshot, shot_id)
    if s is None:
        raise HTTPException(404)
    path = settings.screenshots_dir / s.stored_name
    if not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, media_type="image/png")


# =============================================================== overview / analytics / activity

def _submitted_ever(db: Session) -> int:
    return db.scalar(select(func.count(Application.id)).where(Application.submitted_at.is_not(None))) or 0


@api.get("/overview")
def overview(db: Session = Depends(get_db)):
    now = utcnow()
    week = now - timedelta(days=7)
    stage = dict(db.execute(select(Job.stage, func.count()).group_by(Job.stage)).all())
    live = (Job.is_active.is_(True), Job.eligibility != "rejected", Job.stage != "archived")
    submitted = _submitted_ever(db)
    responded = db.scalar(select(func.count(Application.id)).join(Job, Application.job_id == Job.id)
                          .where(Application.submitted_at.is_not(None), Job.stage.in_(("interview", "offer", "rejected")))) or 0
    by_country = db.execute(select(Job.country, func.count()).join(Application, Application.job_id == Job.id)
                            .where(Application.submitted_at.is_not(None)).group_by(Job.country).order_by(func.count().desc())).all()
    visa = db.execute(select(Job.visa_status, func.count()).where(*live).group_by(Job.visa_status)).all()
    elig = dict(db.execute(select(Job.eligibility, func.count()).where(Job.is_active.is_(True), Job.stage != "archived").group_by(Job.eligibility)).all())
    trend_rows = db.execute(select(func.date(Job.discovered_at), func.count()).where(Job.discovered_at >= now - timedelta(days=30))
                            .group_by(func.date(Job.discovered_at))).all()
    opp_country = db.execute(select(Job.country, func.count()).where(*live).group_by(Job.country).order_by(func.count().desc()).limit(8)).all()
    runs = get_setting(db, "last_runs") or {}
    sched = get_setting(db, "schedule")
    return {
        "metrics": {
            "jobs_discovered": db.scalar(select(func.count(Job.id))) or 0,
            "active_jobs": db.scalar(select(func.count(Job.id)).where(Job.is_active.is_(True))) or 0,
            "new_verified_matches": db.scalar(select(func.count(Job.id)).where(*live, Job.discovered_at >= week)) or 0,
            "high_fit": db.scalar(select(func.count(Job.id)).where(*live, Job.fit_stars >= 4)) or 0,
            "needs_review": elig.get("needs_review", 0), "eligible": elig.get("eligible", 0), "rejected_by_filter": elig.get("rejected", 0),
            "applications_prepared": db.scalar(select(func.count(Application.id))) or 0,
            "awaiting_approval": db.scalar(select(func.count(Application.id)).where(Application.status == "awaiting_approval")) or 0,
            "submitted": submitted,
            "interviews": stage.get("interview", 0), "offers": stage.get("offer", 0), "rejections": stage.get("rejected", 0),
            "response_rate": round(responded / submitted, 3) if submitted else None,
            "sources": db.scalar(select(func.count(Company.id)).where(Company.enabled.is_(True))) or 0,
        },
        "applications_by_country": [{"country": c or "Unknown", "count": n} for c, n in by_country],
        "opportunities_by_country": [{"country": c or "Unknown", "count": n} for c, n in opp_country],
        "visa_breakdown": [{"status": s, "label": VISA_LABEL.get(s, s), "count": n} for s, n in visa],
        "discovery_trend": [{"date": d, "count": n} for d, n in sorted(trend_rows)],
        "pipeline_counts": {s: stage.get(s, 0) for s in pipeline.STAGES},
        "last_runs": runs, "schedule": sched,
        "profile_gaps": profile_gaps(load_profile(db)),
        "has_cv": bool(db.scalar(select(func.count(Document.id)).where(Document.kind == "cv"))),
        "recent_activity": [{"id": e.id, "type": e.type, "message": e.message, "level": e.level, "created_at": iso(e.created_at),
                             "job_id": e.job_id, "application_id": e.application_id}
                            for e in db.scalars(select(Event).order_by(Event.id.desc()).limit(12))],
    }


def _week(dt) -> str:
    monday = dt - timedelta(days=dt.weekday())
    return monday.strftime("%Y-%m-%d")


@api.get("/analytics")
def analytics(db: Session = Depends(get_db)):
    live = (Job.is_active.is_(True), Job.eligibility != "rejected", Job.stage != "archived")
    submitted_apps = db.scalars(select(Application).where(Application.submitted_at.is_not(None))).all()
    per_week = Counter(_week(a.submitted_at) for a in submitted_apps)
    submitted = len(submitted_apps)
    interviewed_ids = {e.job_id for e in db.scalars(select(Event).where(Event.type == "pipeline.moved")) if (e.data or {}).get("to") in ("interview", "offer")}
    interviewed_ids |= {m.application_id and db.get(Application, m.application_id).job_id for m in
                        db.scalars(select(EmailMessage).where(EmailMessage.category == "interview", EmailMessage.applied_to_pipeline.is_(True)))}
    interviewed = len([a for a in submitted_apps if a.job_id in interviewed_ids or a.job.stage in ("interview", "offer")])
    rej_week = Counter()
    for e in db.scalars(select(Event).where(Event.type == "pipeline.moved")):
        if (e.data or {}).get("to") == "rejected":
            rej_week[_week(e.created_at)] += 1
    for m in db.scalars(select(EmailMessage).where(EmailMessage.category == "rejection", EmailMessage.applied_to_pipeline.is_(True))):
        rej_week[_week(m.received_at or m.created_at)] += 1
    countries = db.execute(select(Job.country, func.count()).where(*live).group_by(Job.country).order_by(func.count().desc()).limit(12)).all()
    visa = db.execute(select(Job.visa_status, func.count()).where(*live).group_by(Job.visa_status)).all()
    stars = db.execute(select(Job.fit_stars, func.count()).where(*live).group_by(Job.fit_stars)).all()
    avg_fit = db.scalar(select(func.avg(Job.fit_stars)).where(*live))
    filt = Counter()
    for (reasons,) in db.execute(select(Job.eligibility_reasons).where(Job.eligibility == "rejected", Job.is_active.is_(True))):
        for r in reasons or []:
            if r.get("severity") == "reject":
                filt[r.get("code", "other")] += 1
    labels = {"senior_title": "Senior-level title", "years": "Too many years required", "no_sponsorship": "No sponsorship / needs local authorization",
              "closed": "Closed", "unpaid": "Unpaid", "phd": "PhD required", "clearance": "Security clearance required"}
    ai_rows = db.execute(select(func.date(AIUsage.created_at), func.count(), func.coalesce(func.sum(AIUsage.est_cost_usd), 0))
                         .where(AIUsage.cached.is_(False)).group_by(func.date(AIUsage.created_at))).all()
    by_purpose = db.execute(select(AIUsage.purpose, func.count(), func.coalesce(func.sum(AIUsage.est_cost_usd), 0))
                            .where(AIUsage.cached.is_(False)).group_by(AIUsage.purpose)).all()
    return {
        "applications_over_time": [{"week": w, "count": n} for w, n in sorted(per_week.items())],
        "submitted": submitted,
        "interview_conversion": round(interviewed / submitted, 3) if submitted else None,
        "interviews_reached": interviewed,
        "rejection_trend": [{"week": w, "count": n} for w, n in sorted(rej_week.items())],
        "countries": [{"country": c or "Unknown", "count": n} for c, n in countries],
        "visa_distribution": [{"status": s, "label": VISA_LABEL.get(s, s), "count": n} for s, n in visa],
        "fit_distribution": [{"stars": s, "count": n} for s, n in sorted(stars)],
        "average_fit": round(float(avg_fit), 2) if avg_fit is not None else None,
        "filter_reasons": [{"code": c, "label": labels.get(c, c), "count": n} for c, n in filt.most_common()],
        "ai": {**ai.status(db), "by_day": [{"date": d, "calls": c, "est_cost_usd": round(float(u), 4)} for d, c, u in sorted(ai_rows)],
               "by_purpose": [{"purpose": p, "calls": c, "est_cost_usd": round(float(u), 4)} for p, c, u in by_purpose]},
    }


@api.get("/events")
def events(after: int = 0, limit: int = Query(60, ge=1, le=200), type: str = "", db: Session = Depends(get_db)):
    stmt = select(Event)
    if after:
        stmt = stmt.where(Event.id > after)
    if type:
        stmt = stmt.where(Event.type.like(f"{type}%"))
    rows = db.scalars(stmt.order_by(Event.id.desc()).limit(limit)).all()
    running = db.scalars(select(Task).where(Task.status.in_(("running", "queued"))).order_by(Task.id)).all()
    return {"events": [{"id": e.id, "type": e.type, "message": e.message, "level": e.level, "created_at": iso(e.created_at),
                        "job_id": e.job_id, "application_id": e.application_id} for e in rows],
            "tasks": [{"id": t.id, "type": t.type, "status": t.status, "started_at": iso(t.started_at), "created_at": iso(t.created_at)} for t in running]}


@api.get("/tasks")
def tasks(db: Session = Depends(get_db)):
    rows = db.scalars(select(Task).order_by(Task.id.desc()).limit(50)).all()
    return [{"id": t.id, "type": t.type, "status": t.status, "attempts": t.attempts, "error": t.error, "result": t.result,
             "created_at": iso(t.created_at), "started_at": iso(t.started_at), "finished_at": iso(t.finished_at)} for t in rows]


@api.get("/notifications")
def notifications(db: Session = Depends(get_db)):
    rows = db.scalars(select(Notification).order_by(Notification.id.desc()).limit(60)).all()
    unread = db.scalar(select(func.count(Notification.id)).where(Notification.read.is_(False))) or 0
    return {"unread": unread, "items": [{"id": n.id, "kind": n.kind, "title": n.title, "body": n.body, "read": n.read, "job_id": n.job_id,
                                         "application_id": n.application_id, "created_at": iso(n.created_at)} for n in rows]}


class ReadIn(BaseModel):
    ids: Optional[list[int]] = None


@api.post("/notifications/read")
def read_notifications(body: ReadIn, db: Session = Depends(get_db)):
    stmt = select(Notification).where(Notification.read.is_(False))
    if body.ids:
        stmt = stmt.where(Notification.id.in_(body.ids))
    for n in db.scalars(stmt):
        n.read = True
    db.commit()
    return {"ok": True}


# =============================================================== sources & discovery

def _company_json(c: Company, counts: dict) -> dict:
    return {"id": c.id, "name": c.name, "provider": c.provider, "board_token": c.board_token, "enabled": c.enabled,
            "last_fetch_at": iso(c.last_fetch_at), "last_status": c.last_status, "last_job_count": c.last_job_count,
            "fail_count": c.fail_count, "relevant_jobs": counts.get(c.id, 0)}


@api.get("/companies")
def companies(db: Session = Depends(get_db)):
    counts = dict(db.execute(select(Job.company_id, func.count()).where(Job.is_active.is_(True), Job.eligibility != "rejected").group_by(Job.company_id)).all())
    return [_company_json(c, counts) for c in db.scalars(select(Company).order_by(Company.name))]


class CompanyIn(BaseModel):
    provider: str = Field(pattern="^(greenhouse|lever|ashby)$")
    board_token: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9._\-]+$")
    name: str = Field("", max_length=160)


@api.post("/companies")
def add_company(body: CompanyIn, request: Request, db: Session = Depends(get_db)):
    """Add a source. The board is checked against the official API first: unknown boards are refused."""
    if db.scalar(select(Company.id).where(Company.provider == body.provider, Company.board_token == body.board_token)):
        raise HTTPException(409, {"message": "This source already exists.", "code": "exists"})
    client = PoliteClient()
    try:
        adapter = ADAPTERS[body.provider]
        jobs = adapter.fetch(client, body.board_token)
        name = body.name or adapter.board_name(client, body.board_token) or body.board_token.replace("-", " ").title()
    except SourceError as e:
        raise HTTPException(400, {"message": f"Could not verify this board on {body.provider}: {e}", "code": "unverified"})
    finally:
        client.close()
    c = Company(name=name, provider=body.provider, board_token=body.board_token, last_job_count=len(jobs), last_status="added")
    db.add(c)
    audit(db, _actor(request), "company.add", detail={"provider": body.provider, "token": body.board_token})
    db.flush()
    enqueue(db, "discovery", {"company_ids": [c.id], "trigger": "source added"})
    db.commit()
    return _company_json(c, {})


class CompanyPatch(BaseModel):
    enabled: Optional[bool] = None
    name: Optional[str] = Field(None, max_length=160)


@api.patch("/companies/{cid}")
def patch_company(cid: int, body: CompanyPatch, db: Session = Depends(get_db)):
    c = db.get(Company, cid)
    if c is None:
        raise HTTPException(404)
    if body.enabled is not None:
        c.enabled = body.enabled
    if body.name:
        c.name = body.name
    db.commit()
    return _company_json(c, {})


class RunIn(BaseModel):
    company_ids: Optional[list[int]] = None


@api.post("/discovery/run")
def run_discovery_now(body: RunIn, request: Request, db: Session = Depends(get_db)):
    if db.scalar(select(Task.id).where(Task.type == "discovery", Task.status.in_(("queued", "running")))):
        raise HTTPException(409, {"message": "A job search is already running.", "code": "busy"})
    t = enqueue(db, "discovery", {"company_ids": body.company_ids, "trigger": "manual"})
    audit(db, _actor(request), "discovery.run")
    db.commit()
    return {"task_id": t.id}


# =============================================================== settings

EDITABLE = ("schedule", "search", "ai", "notifications", "automation")


@api.get("/settings")
def get_settings_api(db: Session = Depends(get_db)):
    tg = emailing.telegram_config(db)
    oc = emailing.oauth_config(db)
    return {
        **{k: get_setting(db, k) for k in EDITABLE},
        "ai_status": ai.status(db),
        "telegram": {"configured": bool(tg), "chat_id": tg["chat_id"] if tg else ""},
        "google_oauth": {"configured": bool(oc), "client_id": oc["client_id"] if oc else "", "redirect_uri": emailing.redirect_uri() if settings.public_base_url else "",
                         "public_base_url": settings.public_base_url},
        "server": {"allow_real_submit": settings.allow_real_submit, "ai_mode": settings.ai_mode, "cookie_secure": settings.cookie_secure},
        "last_runs": get_setting(db, "last_runs") or {},
    }


class SettingsIn(BaseModel):
    schedule: Optional[dict] = None
    search: Optional[dict] = None
    ai: Optional[dict] = None
    notifications: Optional[dict] = None
    automation: Optional[dict] = None


def _clean(key: str, incoming: dict) -> dict:
    """Accept only known keys with the right type and sane bounds."""
    base = DEFAULT_SETTINGS[key]
    out = {}
    for k, default in base.items():
        if k not in incoming:
            continue
        v = incoming[k]
        if isinstance(default, bool):
            out[k] = bool(v)
        elif isinstance(default, (int, float)):
            try:
                num = float(v)
            except (TypeError, ValueError):
                raise HTTPException(400, f"{key}.{k} must be a number")
            if num < 0 or num > 100000:
                raise HTTPException(400, f"{key}.{k} is out of range")
            out[k] = int(num) if isinstance(default, int) else num
        elif isinstance(default, list):
            if not isinstance(v, list):
                raise HTTPException(400, f"{key}.{k} must be a list")
            out[k] = [str(x)[:60] for x in v][:40]
        else:
            out[k] = v
    return out


@api.put("/settings")
def put_settings(body: SettingsIn, request: Request, db: Session = Depends(get_db)):
    for key in EDITABLE:
        incoming = getattr(body, key)
        if incoming is None:
            continue
        merged = get_setting(db, key)
        merged.update(_clean(key, incoming))
        set_setting(db, key, merged)
        audit(db, _actor(request), "settings.update", key, detail=_clean(key, incoming), ip=client_ip(request))
    db.commit()
    return get_settings_api(db)


class TelegramIn(BaseModel):
    bot_token: str = Field(min_length=20, max_length=120, pattern=r"^\d+:[A-Za-z0-9_\-]+$")
    chat_id: str = Field(min_length=1, max_length=40, pattern=r"^-?\d+$")


@api.put("/settings/telegram")
def put_telegram(body: TelegramIn, request: Request, db: Session = Depends(get_db)):
    emailing.set_telegram_config(db, body.bot_token, body.chat_id)
    audit(db, _actor(request), "settings.telegram")
    db.commit()
    ok = emailing.telegram_send(db, "SONIC JOBS is connected. You will receive alerts here.")
    return {"configured": True, "test_sent": ok}


@api.delete("/settings/telegram")
def delete_telegram(db: Session = Depends(get_db)):
    set_setting(db, "telegram_secret", "")
    n = get_setting(db, "notifications")
    n["telegram_enabled"] = False
    set_setting(db, "notifications", n)
    db.commit()
    return {"configured": False}


class GoogleIn(BaseModel):
    client_id: str = Field(min_length=10, max_length=200)
    client_secret: str = Field(min_length=6, max_length=200)


@api.put("/settings/google-oauth")
def put_google(body: GoogleIn, request: Request, db: Session = Depends(get_db)):
    emailing.set_oauth_config(db, body.client_id, body.client_secret)
    audit(db, _actor(request), "settings.google_oauth")
    db.commit()
    return {"configured": True}


# =============================================================== email

def _email_json(m: EmailMessage) -> dict:
    return {"id": m.id, "from": m.from_addr, "subject": m.subject, "snippet": m.snippet, "received_at": iso(m.received_at),
            "category": m.category, "confidence": m.confidence, "application_id": m.application_id,
            "match_confidence": m.match_confidence, "match_reason": m.match_reason, "manually_corrected": m.manually_corrected,
            "applied_to_pipeline": m.applied_to_pipeline}


@api.get("/email/status")
def email_status(db: Session = Depends(get_db)):
    return {"oauth_configured": bool(emailing.oauth_config(db)), "public_base_url": settings.public_base_url,
            "accounts": [{"id": a.id, "email": a.email, "last_sync_at": iso(a.last_sync_at), "last_error": a.last_error, "scopes": a.scopes}
                         for a in db.scalars(select(EmailAccount))],
            "scope": emailing.SCOPE}


@api.get("/email/oauth/start")
def email_oauth_start(db: Session = Depends(get_db)):
    try:
        return {"url": emailing.auth_start_url(db)}
    except ValueError as e:
        raise HTTPException(409, {"message": str(e), "code": "not_configured"})


@public.get("/email/oauth/callback")
def email_oauth_callback(request: Request, code: str = "", state: str = "", error: str = "", db: Session = Depends(get_db)):
    # Google redirects here; a valid single-use state plus a logged-in session are both required.
    if lookup_session(db, request.cookies.get(SESSION_COOKIE)) is None:
        return RedirectResponse("/login/", status_code=303)
    if error or not code:
        return RedirectResponse("/settings/?gmail=denied", status_code=303)
    try:
        emailing.complete_oauth(db, code, state)
    except ValueError as e:
        log.warning("gmail oauth failed: %s", e)
        return RedirectResponse("/settings/?gmail=failed", status_code=303)
    return RedirectResponse("/settings/?gmail=connected", status_code=303)


@api.delete("/email/accounts/{aid}")
def email_disconnect(aid: int, request: Request, db: Session = Depends(get_db)):
    a = db.get(EmailAccount, aid)
    if a:
        db.delete(a)
        audit(db, _actor(request), "email.disconnect", a.email)
        db.commit()
    return {"ok": True}


@api.post("/email/sync")
def email_sync(db: Session = Depends(get_db)):
    if not db.scalar(select(EmailAccount.id).limit(1)):
        raise HTTPException(409, {"message": "No Gmail account connected.", "code": "not_configured"})
    t = enqueue(db, "email_sync", {}, dedupe_key="email_sync")
    db.commit()
    return {"task_id": t.id}


@api.get("/emails")
def emails(db: Session = Depends(get_db)):
    return [_email_json(m) for m in db.scalars(select(EmailMessage).order_by(EmailMessage.received_at.desc()).limit(100))]


class EmailPatch(BaseModel):
    category: Optional[str] = Field(None, pattern="^(confirmation|interview|rejection|offer|documents|recruiter_reply|other)$")
    application_id: Optional[int] = None
    unlink: bool = False


@api.patch("/emails/{eid}")
def patch_email(eid: int, body: EmailPatch, db: Session = Depends(get_db)):
    m = db.get(EmailMessage, eid)
    if m is None:
        raise HTTPException(404)
    if body.category:
        m.category, m.confidence = body.category, 1.0
    if body.unlink:
        m.application_id, m.match_confidence, m.match_reason = None, 0, "unlinked manually"
    elif body.application_id is not None:
        if db.get(Application, body.application_id) is None:
            raise HTTPException(400, "Unknown application")
        m.application_id, m.match_confidence, m.match_reason = body.application_id, 1.0, "linked manually"
    m.manually_corrected = True
    db.commit()
    return _email_json(m)


@api.get("/audit")
def audit_log(db: Session = Depends(get_db)):
    return [{"id": a.id, "actor": a.actor, "action": a.action, "target": a.target, "ip": a.ip, "created_at": iso(a.created_at)}
            for a in db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(100))]


app.include_router(public)
app.include_router(api)


@app.exception_handler(404)
async def not_found(request: Request, exc):
    if request.url.path.startswith("/api"):
        return JSONResponse({"detail": getattr(exc, "detail", "Not found")}, status_code=404)
    page = settings.frontend_dir / "404.html"
    if page.is_file():
        return FileResponse(page, status_code=404)
    return JSONResponse({"detail": "Not found"}, status_code=404)


if settings.frontend_dir.is_dir():
    app.mount("/", StaticFiles(directory=str(settings.frontend_dir), html=True), name="frontend")
