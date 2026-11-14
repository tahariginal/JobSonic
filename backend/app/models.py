from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base, utcnow


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    csrf_token: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    user_agent: Mapped[str] = mapped_column(String(255), default="")


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Profile(Base):
    """Single-row candidate profile. `data` is validated by schemas.ProfileData."""

    __tablename__ = "profile"
    id: Mapped[int] = mapped_column(primary_key=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(24))  # cv | cover_letter | other
    label: Mapped[str] = mapped_column(String(160))
    tags: Mapped[list] = mapped_column(JSON, default=list)
    filename: Mapped[str] = mapped_column(String(255))
    stored_name: Mapped[str] = mapped_column(String(80))
    mime: Mapped[str] = mapped_column(String(80))
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Company(Base):
    __tablename__ = "companies"
    __table_args__ = (UniqueConstraint("provider", "board_token"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    provider: Mapped[str] = mapped_column(String(24))  # greenhouse | lever | ashby
    board_token: Mapped[str] = mapped_column(String(120))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_fetch_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_status: Mapped[str] = mapped_column(String(255), default="")
    last_job_count: Mapped[int] = mapped_column(Integer, default=0)
    fail_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("provider", "company_id", "external_id"),
        Index("ix_jobs_stage", "stage"),
        Index("ix_jobs_elig", "eligibility"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    company: Mapped[Company] = relationship(lazy="joined")
    provider: Mapped[str] = mapped_column(String(24))
    external_id: Mapped[str] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(300))
    canonical_url: Mapped[str] = mapped_column(String(600), index=True)
    apply_url: Mapped[str] = mapped_column(String(600))
    source_url: Mapped[str] = mapped_column(String(600))
    location_raw: Mapped[str] = mapped_column(String(400), default="")
    country: Mapped[str] = mapped_column(String(60), default="", index=True)
    region: Mapped[str] = mapped_column(String(24), default="")
    remote_mode: Mapped[str] = mapped_column(String(16), default="unknown")  # onsite|hybrid|remote|unknown
    remote_scope: Mapped[str] = mapped_column(String(40), default="")
    department: Mapped[str] = mapped_column(String(200), default="")
    employment_type: Mapped[str] = mapped_column(String(60), default="")
    description_text: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    salary_text: Mapped[str] = mapped_column(String(200), default="")
    salary_min: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    salary_max: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    salary_currency: Mapped[str] = mapped_column(String(8), default="")
    posted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    updated_content_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # --- analysis (deterministic unless *_source says otherwise) ---
    role_family: Mapped[str] = mapped_column(String(40), default="")
    experience_level: Mapped[str] = mapped_column(String(16), default="unknown")
    min_years: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    eligibility: Mapped[str] = mapped_column(String(16), default="unevaluated")
    eligibility_reasons: Mapped[list] = mapped_column(JSON, default=list)
    visa_status: Mapped[str] = mapped_column(String(16), default="unverified")
    visa_evidence: Mapped[list] = mapped_column(JSON, default=list)
    visa_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    relocation: Mapped[str] = mapped_column(String(16), default="unverified")
    relocation_evidence: Mapped[list] = mapped_column(JSON, default=list)
    remote_from_morocco: Mapped[str] = mapped_column(String(16), default="unverified")
    fit_stars: Mapped[int] = mapped_column(Integer, default=0, index=True)
    fit_score: Mapped[float] = mapped_column(Float, default=0)
    fit_reason: Mapped[str] = mapped_column(Text, default="")
    fit_breakdown: Mapped[dict] = mapped_column(JSON, default=dict)
    analysis_source: Mapped[str] = mapped_column(String(12), default="rules")  # rules | ai
    ai_notes: Mapped[str] = mapped_column(Text, default="")

    # --- user state ---
    stage: Mapped[str] = mapped_column(String(24), default="discovered")
    saved: Mapped[bool] = mapped_column(Boolean, default=False)
    seen: Mapped[bool] = mapped_column(Boolean, default=False)
    manual_override: Mapped[bool] = mapped_column(Boolean, default=False)


class Application(Base):
    __tablename__ = "applications"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), unique=True)
    job: Mapped[Job] = relationship(lazy="joined")
    status: Mapped[str] = mapped_column(String(24), default="draft")
    automation_mode: Mapped[str] = mapped_column(String(16), default="manual", server_default="manual")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    cv_document_id: Mapped[Optional[int]] = mapped_column(ForeignKey("documents.id"), nullable=True)
    cover_letter: Mapped[str] = mapped_column(Text, default="")
    fit_pitch: Mapped[str] = mapped_column(Text, default="")
    answers: Mapped[list] = mapped_column(JSON, default=list)
    form_schema: Mapped[dict] = mapped_column(JSON, default=dict)
    issues: Mapped[list] = mapped_column(JSON, default=list)
    fill_report: Mapped[dict] = mapped_column(JSON, default=dict)
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    approved_revision: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    approved_hash: Mapped[str] = mapped_column(String(64), default="")
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    submit_key: Mapped[str] = mapped_column(String(64), default="")
    submit_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    submitted_via: Mapped[str] = mapped_column(String(16), default="")  # agent | manual
    confirmation: Mapped[dict] = mapped_column(JSON, default=dict)
    last_error: Mapped[str] = mapped_column(Text, default="")
    materials_source: Mapped[str] = mapped_column(String(12), default="template")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class MaterialVersion(Base):
    __tablename__ = "material_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64))
    snapshot: Mapped[dict] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ApprovalEvent(Base):
    __tablename__ = "approval_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(24))  # approve|reject|request_changes|invalidated
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Screenshot(Base):
    __tablename__ = "screenshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(24))  # filled | pre_submit | confirmation | error
    stored_name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Note(Base):
    __tablename__ = "notes"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Event(Base):
    """Real backend activity. The dashboard feed and timelines read only from here."""

    __tablename__ = "events"
    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(48), index=True)
    message: Mapped[str] = mapped_column(String(500))
    level: Mapped[str] = mapped_column(String(8), default="info")
    job_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    application_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")
    job_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    application_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    dedupe_key: Mapped[str] = mapped_column(String(160), unique=True)
    read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(40), index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(12), default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=1)
    run_after: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    dedupe_key: Mapped[str] = mapped_column(String(160), default="", index=True)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class AIUsage(Base):
    __tablename__ = "ai_usage"
    id: Mapped[int] = mapped_column(primary_key=True)
    purpose: Mapped[str] = mapped_column(String(40))
    mode: Mapped[str] = mapped_column(String(16))
    model: Mapped[str] = mapped_column(String(60), default="")
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    est_cost_usd: Mapped[float] = mapped_column(Float, default=0)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    cached: Mapped[bool] = mapped_column(Boolean, default=False)
    job_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    error: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class AICache(Base):
    __tablename__ = "ai_cache"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    purpose: Mapped[str] = mapped_column(String(40))
    result: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class EmailAccount(Base):
    __tablename__ = "email_accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(200), unique=True)
    encrypted_token: Mapped[str] = mapped_column(Text)
    scopes: Mapped[str] = mapped_column(String(400), default="")
    last_sync_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str] = mapped_column(String(400), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class EmailMessage(Base):
    __tablename__ = "email_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    gmail_id: Mapped[str] = mapped_column(String(64), unique=True)
    thread_id: Mapped[str] = mapped_column(String(64), default="")
    from_addr: Mapped[str] = mapped_column(String(300), default="")
    subject: Mapped[str] = mapped_column(String(500), default="")
    snippet: Mapped[str] = mapped_column(Text, default="")
    received_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    category: Mapped[str] = mapped_column(String(24), default="other")
    confidence: Mapped[float] = mapped_column(Float, default=0)
    application_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    match_confidence: Mapped[float] = mapped_column(Float, default=0)
    match_reason: Mapped[str] = mapped_column(String(300), default="")
    manually_corrected: Mapped[bool] = mapped_column(Boolean, default=False)
    applied_to_pipeline: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(80), index=True)
    target: Mapped[str] = mapped_column(String(120), default="")
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    ip: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
