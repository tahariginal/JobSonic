"""Shared helpers: settings store, activity events, notifications, audit log, task queue."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import utcnow
from .models import AuditLog, Event, Notification, Setting, Task

log = logging.getLogger("sonic")

DEFAULT_SETTINGS: dict[str, Any] = {
    "schedule": {
        "discovery_enabled": True,
        "discovery_interval_hours": 12,
        "verify_enabled": True,
        "verify_interval_hours": 24,
        "email_sync_enabled": True,
        "email_sync_interval_minutes": 30,
    },
    "search": {
        "extra_title_keywords": [],
        "exclude_title_keywords": [],
        "max_years_experience": 2,
    },
    "ai": {
        "enabled": False,
        "daily_call_budget": 25,
        "monthly_call_budget": 300,
        "daily_usd_budget": 1.0,
        "monthly_usd_budget": 10.0,
        "min_stars_for_ai": 4,
        "auto_evaluate": False,
    },
    "notifications": {
        "min_stars": 4,
        "telegram_enabled": False,
    },
    "automation": {
        "max_form_seconds": 120,
    },
    "last_runs": {},
}

SECRET_SETTING_KEYS = {"telegram_secret", "google_oauth_secret"}


def get_setting(db: Session, key: str) -> Any:
    row = db.get(Setting, key)
    default = DEFAULT_SETTINGS.get(key)
    if row is None:
        return dict(default) if isinstance(default, dict) else default
    if isinstance(default, dict) and isinstance(row.value, dict):
        merged = dict(default)
        merged.update(row.value)
        return merged
    return row.value


def set_setting(db: Session, key: str, value: Any) -> None:
    row = db.get(Setting, key)
    if row is None:
        db.add(Setting(key=key, value=value))
    else:
        row.value = value
        row.updated_at = utcnow()


def emit(
    db: Session,
    type: str,
    message: str,
    *,
    level: str = "info",
    job_id: Optional[int] = None,
    application_id: Optional[int] = None,
    data: Optional[dict] = None,
) -> Event:
    ev = Event(
        type=type,
        message=message[:500],
        level=level,
        job_id=job_id,
        application_id=application_id,
        data=data or {},
    )
    db.add(ev)
    log.info("event %s: %s", type, message)
    return ev


def notify(
    db: Session,
    kind: str,
    title: str,
    body: str = "",
    *,
    dedupe_key: str,
    job_id: Optional[int] = None,
    application_id: Optional[int] = None,
) -> Optional[Notification]:
    """Create a notification once per dedupe_key (no repeated alerts for unchanged things)."""
    exists = db.scalar(select(Notification.id).where(Notification.dedupe_key == dedupe_key))
    if exists:
        return None
    n = Notification(
        kind=kind,
        title=title[:200],
        body=body,
        dedupe_key=dedupe_key[:160],
        job_id=job_id,
        application_id=application_id,
    )
    db.add(n)
    db.flush()
    # Telegram fan-out is queued so a slow network never blocks the caller.
    if get_setting(db, "notifications").get("telegram_enabled"):
        enqueue(db, "telegram_send", {"notification_id": n.id})
    return n


def audit(db: Session, actor: str, action: str, target: str = "", detail: Optional[dict] = None, ip: str = "") -> None:
    db.add(AuditLog(actor=actor, action=action, target=target, detail=detail or {}, ip=ip))


def enqueue(
    db: Session,
    type: str,
    payload: Optional[dict] = None,
    *,
    dedupe_key: str = "",
    max_attempts: int = 1,
    delay_seconds: int = 0,
) -> Task:
    """Queue a background task. With dedupe_key, an identical queued/running task is reused."""
    if dedupe_key:
        existing = db.scalar(
            select(Task).where(Task.dedupe_key == dedupe_key, Task.status.in_(("queued", "running")))
        )
        if existing:
            return existing
    t = Task(
        type=type,
        payload=payload or {},
        dedupe_key=dedupe_key,
        max_attempts=max_attempts,
        run_after=utcnow() + timedelta(seconds=delay_seconds),
    )
    db.add(t)
    db.flush()
    return t


def iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() + "Z" if dt else None
