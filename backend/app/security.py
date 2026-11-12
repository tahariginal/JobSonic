"""Authentication, sessions, CSRF, rate limiting and at-rest encryption."""
from __future__ import annotations

import hashlib
import secrets
import time
from collections import defaultdict, deque
from datetime import timedelta
from typing import Optional

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db, utcnow
from .models import AuthSession, User

SESSION_COOKIE = "sj_session"
_ph = PasswordHasher()


def hash_password(pw: str) -> str:
    return _ph.hash(pw)


def verify_password(hash_: str, pw: str) -> bool:
    try:
        return _ph.verify(hash_, pw)
    except (VerifyMismatchError, Exception):
        return False


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db: Session, user: User, user_agent: str = "") -> tuple[str, AuthSession]:
    token = secrets.token_urlsafe(40)
    s = AuthSession(
        token_hash=_hash_token(token),
        user_id=user.id,
        csrf_token=secrets.token_urlsafe(32),
        expires_at=utcnow() + timedelta(hours=get_settings().session_hours),
        user_agent=user_agent[:255],
    )
    db.add(s)
    db.commit()
    return token, s


def lookup_session(db: Session, token: Optional[str]) -> Optional[AuthSession]:
    if not token:
        return None
    s = db.scalar(select(AuthSession).where(AuthSession.token_hash == _hash_token(token)))
    if s is None or s.expires_at < utcnow():
        return None
    return s


def client_ip(request: Request) -> str:
    # Only trust the proxy header when the direct peer is the local reverse proxy.
    peer = request.client.host if request.client else ""
    if peer in ("127.0.0.1", "::1"):
        fwd = request.headers.get("x-forwarded-for", "")
        if fwd:
            return fwd.split(",")[0].strip()
    return peer


class RateLimiter:
    """Small in-memory sliding-window limiter (single-process app)."""

    def __init__(self) -> None:
        self.hits: dict[str, deque] = defaultdict(deque)

    def check(self, key: str, limit: int, window: float) -> bool:
        now = time.monotonic()
        q = self.hits[key]
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True

    def reset(self) -> None:
        self.hits.clear()


limiter = RateLimiter()


def require_session(request: Request, db: Session = Depends(get_db)) -> AuthSession:
    """Dependency for every protected endpoint: valid session + CSRF on unsafe methods."""
    s = lookup_session(db, request.cookies.get(SESSION_COOKIE))
    if s is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        sent = request.headers.get("x-csrf-token", "")
        if not sent or not secrets.compare_digest(sent, s.csrf_token):
            raise HTTPException(status_code=403, detail="CSRF token missing or invalid")
    if not limiter.check(f"api:{s.id}", 600, 60):
        raise HTTPException(status_code=429, detail="Too many requests")
    now = utcnow()
    if (now - s.last_seen_at).total_seconds() > 300:
        s.last_seen_at = now
        db.commit()
    request.state.session = s
    return s


# ---- encryption of secrets at rest -------------------------------------------------

def _fernet() -> Fernet:
    key = get_settings().encryption_key
    if not key:
        raise RuntimeError("SONIC_ENCRYPTION_KEY is not configured")
    return Fernet(key.encode())


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> Optional[str]:
    try:
        return _fernet().decrypt(value.encode()).decode()
    except (InvalidToken, RuntimeError):
        return None
