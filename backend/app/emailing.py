"""Gmail integration (read-only OAuth), email classification and matching to applications.

Scope requested: gmail.readonly only. This module cannot send, reply, label or delete mail.
Tokens are stored encrypted (Fernet) and never returned by the API.
"""
from __future__ import annotations

import json
import re
import secrets
from datetime import datetime, timezone
from email.utils import parseaddr, parsedate_to_datetime
from typing import Optional
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .core import emit, get_setting, notify, set_setting
from .db import utcnow
from .models import Application, EmailAccount, EmailMessage
from .security import decrypt, encrypt

SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://gmail.googleapis.com/gmail/v1/users/me"

RULES: list[tuple[str, float, re.Pattern]] = [
    ("rejection", 0.92, re.compile(
        r"regret to inform|not (be )?(moving|proceeding|progressing) (forward|ahead)|decided to (move|proceed|go) (forward |ahead )?with other|"
        r"(pursue|proceed with|move forward with) other (candidates|applicants)|will not be (moving|proceeding|progressing)|"
        r"won.t be (moving|proceeding|progressing)|not (been )?selected|unsuccessful on this occasion|we are unable to offer you|"
        r"not to (move|proceed) (forward |ahead )?with your (application|candidacy)", re.I)),
    ("offer", 0.9, re.compile(
        r"pleased to offer|delighted to offer|happy to offer you|offer of employment|your offer letter|we would like to (extend|make) (you )?an offer|"
        r"extend(ing)? (you )?an offer|formal offer", re.I)),
    ("interview", 0.88, re.compile(
        r"(schedule|book|arrange|set up) (an?|your|the) (interview|call|chat|conversation|screen)|invite you (to|for) (an?|the) (interview|call|chat|technical|next)|"
        r"interview (invitation|request|with)|your availability|phone screen|next (round|stage) of (the |our )?(interview|process)|"
        r"(coding|technical|online) (challenge|assessment|test)|take[- ]home|would like to (speak|talk|chat) with you", re.I)),
    ("documents", 0.8, re.compile(
        r"(additional|further|more|missing) (documents?|information|details)|please (send|provide|share|upload|complete)\b.{0,40}(transcript|certificate|portfolio|reference|document|form|id|passport)", re.I)),
    ("confirmation", 0.85, re.compile(
        r"thank you for (applying|your application|your interest in)|thanks for (applying|your application)|application (has been |was )?(received|submitted)|"
        r"we(.ve| have) received your application|successfully (applied|submitted)|we will review your application", re.I)),
    ("rejection", 0.6, re.compile(r"\bunfortunately\b|other candidates|position has been filled", re.I)),
    ("interview", 0.55, re.compile(r"\binterview\b|next steps?", re.I)),
]
NOREPLY = re.compile(r"no-?reply|do-?not-?reply|notifications?@|mailer|jobs-noreply", re.I)
STOP = {"inc", "ltd", "gmbh", "llc", "the", "sas", "bv", "ag", "co", "company", "group", "technologies", "technology", "labs", "team", "careers", "recruiting", "hiring", "talent"}


def classify(subject: str, snippet: str) -> tuple[str, float]:
    text = f"{subject}\n{snippet}"
    best = ("other", 0.0)
    for cat, conf, pat in RULES:
        if pat.search(text) and conf > best[1]:
            best = (cat, conf)
    # a confirmation that also contains a strong rejection phrase is a rejection; the reverse is handled by rule order
    return best


def _name_tokens(name: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", (name or "").lower()) if len(t) > 1 and t not in STOP]


def match_application(db: Session, from_addr: str, subject: str, snippet: str, apps: Optional[list[Application]] = None) -> tuple[Optional[Application], float, str]:
    """Best matching application with a confidence and a human-readable reason."""
    display, addr = parseaddr(from_addr)
    domain = addr.split("@")[-1].lower() if "@" in addr else ""
    hay_sender = f"{display} {domain}".lower()
    hay_text = f"{subject} {snippet}".lower()
    if apps is None:
        apps = list(db.scalars(select(Application).where(Application.status.in_(("submitted", "submit_uncertain", "approved")))))
    best: tuple[Optional[Application], float, str] = (None, 0.0, "")
    for app in apps:
        toks = _name_tokens(app.job.company.name)
        if not toks:
            continue
        comp = " ".join(toks)
        score, why = 0.0, []
        in_sender = comp in re.sub(r"[^a-z0-9]+", " ", hay_sender) or "".join(toks) in re.sub(r"[^a-z0-9]", "", domain.split(".")[0] if domain else "")
        in_text = re.search(rf"\b{re.escape(comp)}\b", re.sub(r"[^a-z0-9]+", " ", hay_text)) is not None
        if in_sender:
            score += 0.6
            why.append("sender matches company")
        elif in_text:
            score += 0.5
            why.append("company named in the message")
        else:
            continue
        title = re.sub(r"[^a-z0-9]+", " ", app.job.title.lower()).strip()
        title_toks = [t for t in title.split() if len(t) > 2]
        text_norm = re.sub(r"[^a-z0-9]+", " ", hay_text)
        if title and title in text_norm:
            score += 0.35
            why.append("role title quoted")
        elif title_toks and sum(t in text_norm.split() for t in title_toks) / len(title_toks) >= 0.6:
            score += 0.2
            why.append("role title partly matches")
        if in_sender and in_text:
            score += 0.05
        score = min(score, 0.99)
        if score > best[1]:
            best = (app, score, ", ".join(why))
    if best[1] < 0.5:
        return None, best[1], best[2]
    return best


def apply_to_pipeline(db: Session, msg: EmailMessage) -> bool:
    """Reflect a clearly classified, clearly matched email in the pipeline. Ambiguous mail only notifies."""
    if msg.application_id is None:
        return False
    app = db.get(Application, msg.application_id)
    if app is None:
        return False
    job = app.job
    label = f"{job.company.name} — {job.title}"
    emit(db, "email.detected", f"Recruiter email detected ({msg.category}, {int(msg.confidence * 100)}%): {label}.",
         job_id=job.id, application_id=app.id, data={"email_id": msg.id})
    strong = msg.confidence >= 0.85 and msg.match_confidence >= 0.6
    moved = False
    if msg.category == "confirmation":
        conf = dict(app.confirmation or {})
        conf["email"] = {"subject": msg.subject, "from": msg.from_addr, "received_at": msg.received_at.isoformat() + "Z" if msg.received_at else None}
        app.confirmation = conf
        if app.status == "submit_uncertain" and strong:
            app.status, app.submitted_at, app.submitted_via = "submitted", msg.received_at or utcnow(), "agent"
            job.stage = "submitted"
            moved = True
    elif msg.category == "interview" and strong and job.stage == "submitted":
        job.stage, moved = "interview", True
    elif msg.category == "rejection" and strong and msg.match_confidence >= 0.7 and job.stage in ("submitted", "interview"):
        job.stage, moved = "rejected", True
    elif msg.category == "offer" and strong and job.stage in ("submitted", "interview"):
        job.stage, moved = "offer", True
    kind = {"interview": "interview", "offer": "offer", "rejection": "rejection", "documents": "documents"}.get(msg.category, "recruiter_reply")
    if msg.category != "confirmation":
        titles = {"interview": "Interview invitation", "offer": "Offer", "rejection": "Rejection", "documents": "Documents requested", "recruiter_reply": "Recruiter reply"}
        notify(db, kind, f"{titles[kind]}: {job.company.name}",
               f"{msg.subject}" + ("" if moved or msg.category in ("documents",) else " — please review; the pipeline was not changed automatically."),
               dedupe_key=f"email:{msg.gmail_id}", job_id=job.id, application_id=app.id)
    msg.applied_to_pipeline = moved
    return moved


def ingest_message(db: Session, *, gmail_id: str, thread_id: str, from_addr: str, subject: str, snippet: str,
                   received_at: Optional[datetime], account_id: Optional[int] = None) -> Optional[EmailMessage]:
    """Classify + match + store one message. Returns None if it is irrelevant or already stored."""
    if db.scalar(select(EmailMessage.id).where(EmailMessage.gmail_id == gmail_id)):
        return None
    category, conf = classify(subject, snippet)
    app, mconf, why = match_application(db, from_addr, subject, snippet)
    if app is None and category == "other":
        return None
    if app is not None and category == "other":
        _, addr = parseaddr(from_addr)
        category, conf = ("recruiter_reply", 0.5) if not NOREPLY.search(addr) else ("other", 0.3)
    # same thread as an already-matched message -> inherit the application
    if app is None and thread_id:
        prev = db.scalar(select(EmailMessage).where(EmailMessage.thread_id == thread_id, EmailMessage.application_id.is_not(None)))
        if prev is not None:
            app, mconf, why = db.get(Application, prev.application_id), 0.7, "same conversation as a matched email"
    msg = EmailMessage(account_id=account_id, gmail_id=gmail_id, thread_id=thread_id, from_addr=from_addr[:300], subject=subject[:500],
                       snippet=snippet, received_at=received_at, category=category, confidence=conf,
                       application_id=app.id if app else None, match_confidence=mconf, match_reason=why[:300])
    db.add(msg)
    db.flush()
    if app is not None:
        apply_to_pipeline(db, msg)
    return msg


# ---------------------------------------------------------------- OAuth

def oauth_config(db: Session) -> Optional[dict]:
    raw = get_setting(db, "google_oauth_secret")
    if not raw:
        return None
    dec = decrypt(raw)
    return json.loads(dec) if dec else None


def set_oauth_config(db: Session, client_id: str, client_secret: str) -> None:
    set_setting(db, "google_oauth_secret", encrypt(json.dumps({"client_id": client_id.strip(), "client_secret": client_secret.strip()})))


def redirect_uri() -> str:
    base = get_settings().public_base_url.rstrip("/")
    return f"{base}/api/email/oauth/callback"


def auth_start_url(db: Session) -> str:
    cfg = oauth_config(db)
    if not cfg:
        raise ValueError("Google OAuth client is not configured")
    if not get_settings().public_base_url:
        raise ValueError("SONIC_PUBLIC_BASE_URL is not set; Google needs a fixed redirect URL")
    state = secrets.token_urlsafe(24)
    set_setting(db, "google_oauth_state", {"state": state, "at": utcnow().isoformat()})
    db.commit()
    return AUTH_URL + "?" + urlencode({
        "client_id": cfg["client_id"], "redirect_uri": redirect_uri(), "response_type": "code", "scope": SCOPE,
        "access_type": "offline", "prompt": "consent", "state": state,
    })


def complete_oauth(db: Session, code: str, state: str, http: Optional[httpx.Client] = None) -> EmailAccount:
    saved = get_setting(db, "google_oauth_state") or {}
    if not state or not secrets.compare_digest(str(saved.get("state", "")), state):
        raise ValueError("OAuth state mismatch")
    set_setting(db, "google_oauth_state", {})
    cfg = oauth_config(db)
    if not cfg:
        raise ValueError("Google OAuth client is not configured")
    own = http is None
    http = http or httpx.Client(timeout=20)
    try:
        r = http.post(TOKEN_URL, data={"code": code, "client_id": cfg["client_id"], "client_secret": cfg["client_secret"],
                                       "redirect_uri": redirect_uri(), "grant_type": "authorization_code"})
        if r.status_code != 200:
            raise ValueError(f"token exchange failed ({r.status_code})")
        tok = r.json()
        if "refresh_token" not in tok:
            raise ValueError("Google did not return a refresh token; remove the app's access in your Google account and retry")
        pr = http.get(f"{API}/profile", headers={"Authorization": f"Bearer {tok['access_token']}"})
        if pr.status_code != 200:
            raise ValueError("could not read the Gmail profile")
        email = pr.json().get("emailAddress", "")
    finally:
        if own:
            http.close()
    acct = db.scalar(select(EmailAccount).where(EmailAccount.email == email))
    enc = encrypt(json.dumps({"refresh_token": tok["refresh_token"]}))
    if acct is None:
        acct = EmailAccount(email=email, encrypted_token=enc, scopes=tok.get("scope", SCOPE))
        db.add(acct)
    else:
        acct.encrypted_token, acct.scopes, acct.last_error = enc, tok.get("scope", SCOPE), ""
    emit(db, "email.connected", f"Gmail connected (read-only): {email}.")
    db.commit()
    return acct


def _access_token(db: Session, acct: EmailAccount, http: httpx.Client) -> str:
    cfg = oauth_config(db)
    dec = decrypt(acct.encrypted_token)
    if not cfg or not dec:
        raise ValueError("stored Gmail credentials cannot be read")
    r = http.post(TOKEN_URL, data={"client_id": cfg["client_id"], "client_secret": cfg["client_secret"],
                                   "refresh_token": json.loads(dec)["refresh_token"], "grant_type": "refresh_token"})
    if r.status_code != 200:
        raise ValueError(f"token refresh failed ({r.status_code}); reconnect Gmail")
    return r.json()["access_token"]


def sync_account(db: Session, acct: EmailAccount, http: Optional[httpx.Client] = None, days: int = 14, limit: int = 60) -> dict:
    own = http is None
    http = http or httpx.Client(timeout=25)
    stats = {"checked": 0, "stored": 0, "matched": 0}
    try:
        token = _access_token(db, acct, http)
        h = {"Authorization": f"Bearer {token}"}
        r = http.get(f"{API}/messages", headers=h, params={"q": f"newer_than:{days}d -category:promotions -category:social -in:sent -in:chats", "maxResults": limit})
        if r.status_code != 200:
            raise ValueError(f"Gmail list failed ({r.status_code})")
        for ref in r.json().get("messages", []) or []:
            stats["checked"] += 1
            if db.scalar(select(EmailMessage.id).where(EmailMessage.gmail_id == ref["id"])):
                continue
            m = http.get(f"{API}/messages/{ref['id']}", headers=h,
                         params=[("format", "metadata"), ("metadataHeaders", "From"), ("metadataHeaders", "Subject"), ("metadataHeaders", "Date")])
            if m.status_code != 200:
                continue
            data = m.json()
            hd = {x["name"].lower(): x["value"] for x in (data.get("payload") or {}).get("headers", [])}
            received = None
            try:
                received = parsedate_to_datetime(hd.get("date", "")).astimezone(timezone.utc).replace(tzinfo=None)
            except (TypeError, ValueError):
                if data.get("internalDate"):
                    received = datetime.fromtimestamp(int(data["internalDate"]) / 1000, tz=timezone.utc).replace(tzinfo=None)
            msg = ingest_message(db, gmail_id=data["id"], thread_id=data.get("threadId", ""), from_addr=hd.get("from", ""),
                                 subject=hd.get("subject", ""), snippet=data.get("snippet", ""), received_at=received, account_id=acct.id)
            if msg is not None:
                stats["stored"] += 1
                stats["matched"] += 1 if msg.application_id else 0
        acct.last_sync_at, acct.last_error = utcnow(), ""
    except (ValueError, httpx.HTTPError) as e:
        acct.last_error = str(e)[:400]
        emit(db, "email.error", f"Gmail sync failed for {acct.email}: {acct.last_error}", level="error")
        stats["error"] = acct.last_error
    finally:
        if own:
            http.close()
    db.commit()
    return stats


def sync_all(db: Session) -> dict:
    out = {}
    for acct in db.scalars(select(EmailAccount)):
        out[acct.email] = sync_account(db, acct)
    return out


# ---------------------------------------------------------------- Telegram (optional)

def telegram_config(db: Session) -> Optional[dict]:
    raw = get_setting(db, "telegram_secret")
    dec = decrypt(raw) if raw else None
    return json.loads(dec) if dec else None


def set_telegram_config(db: Session, bot_token: str, chat_id: str) -> None:
    set_setting(db, "telegram_secret", encrypt(json.dumps({"bot_token": bot_token.strip(), "chat_id": str(chat_id).strip()})))


def telegram_send(db: Session, text: str, http: Optional[httpx.Client] = None) -> bool:
    cfg = telegram_config(db)
    if not cfg:
        return False
    own = http is None
    http = http or httpx.Client(timeout=15)
    try:
        r = http.post(f"https://api.telegram.org/bot{cfg['bot_token']}/sendMessage",
                      json={"chat_id": cfg["chat_id"], "text": text[:3500], "disable_web_page_preview": True})
        return r.status_code == 200
    except httpx.HTTPError:
        return False
    finally:
        if own:
            http.close()
