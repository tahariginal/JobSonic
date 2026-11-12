"""Throw-away SONIC JOBS instance for dashboard end-to-end tests.

Runs on 127.0.0.1:8791 with a temporary database seeded with fixture data. No worker runs,
so nothing can be discovered or submitted; approvals simply stay queued.
"""
import hashlib
import os
import struct
import sys
import tempfile
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TMP = tempfile.mkdtemp(prefix="sonic-e2e-")
os.environ.update({
    "SONIC_DATA_DIR": TMP, "SONIC_ENV": "test", "SONIC_COOKIE_SECURE": "false", "SONIC_SECRET_KEY": "e2e",
    "SONIC_ENCRYPTION_KEY": "x9bP0mW2m0u2W2Yc3m7mJq3r8yq0m0F4n9s8m1Zk1uE=", "SONIC_AI_MODE": "off", "SONIC_PUBLIC_BASE_URL": "",
    "SONIC_FRONTEND_DIR": str(ROOT / "frontend" / "out"), "SONIC_DATABASE_URL": "",
})
sys.path.insert(0, str(ROOT / "backend"))

from app import models  # noqa: E402,F401
from app.core import emit, notify  # noqa: E402
from app.db import Base, SessionLocal, get_engine  # noqa: E402
from app.discovery import apply_analysis  # noqa: E402
from app.models import Company, Document, Job, Profile, Screenshot, User  # noqa: E402
from app.normalize import fingerprint, parse_location, role_family, summarize_role  # noqa: E402
from app.preparation import prepare_application  # noqa: E402
from app.schemas import Language, seed_profile  # noqa: E402
from app.security import hash_password  # noqa: E402
from app.config import get_settings  # noqa: E402

JOBS = [
    ("Acme Robotics", "lever", "acme", "Junior Backend Engineer", "Berlin, Germany", "<h3>What you'll do</h3><ul><li>Build APIs in C++</li><li>Automate deployments</li></ul><p>0-2 years of experience. We offer visa sponsorship and relocation support for this role.</p>"),
    ("Acme Robotics", "lever", "acme", "Senior Platform Engineer", "Berlin, Germany", "<p>8+ years of professional experience required.</p>"),
    ("Globex", "greenhouse", "globex", "Graduate Software Engineer", "Amsterdam, Netherlands", "<p>Join our graduate programme. Sponsorship may be available for exceptional candidates. Bachelor's degree in Computer Science required.</p>"),
    ("Globex", "greenhouse", "globex", "Software Engineer", "London, United Kingdom", "<p>Build backend services. Applicants must have the right to work in the UK.</p>"),
    ("Initech", "ashby", "initech", "AI Agent Engineer", "Remote (Worldwide)", "<p>Work from anywhere in the world on RAG and MCP agents with tool calling. 1+ years of experience.</p>"),
    ("Initech", "ashby", "initech", "Full-Stack Developer", "Tokyo, Japan", "<p>Ship product features end to end. Fluent Japanese is required.</p>"),
    ("Umbrella Labs", "lever", "umbrella", "Entry-Level Software Engineer", "Dubai, United Arab Emirates", "<p>Entry-level role for new graduates. The salary range is $60,000 - $75,000 per year.</p>"),
    ("Umbrella Labs", "lever", "umbrella", "Mobile Engineer (iOS)", "Paris, France", "<p>3+ years of experience building iOS apps.</p>"),
    ("Hooli", "lever", "hooli", "Junior Automation Engineer", "Lisbon, Portugal", "<p>0-1 years of experience. Automation and APIs. Visa sponsorship is available.</p>"),
    ("Hooli", "lever", "hooli", "Backend Engineer", "Toronto, Canada", "<p>2 years of experience with APIs and backend systems. We are unable to sponsor visas for this position.</p>"),
]


def png(w=640, h=900, rgb=(250, 250, 250)) -> bytes:
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)  # noqa: E731
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def seed() -> None:
    s = get_settings()
    Base.metadata.create_all(get_engine())
    db = SessionLocal()
    db.add(User(username="admin", password_hash=hash_password("e2e-password-123")))
    p = seed_profile()
    p.personal.first_name, p.personal.last_name, p.personal.email, p.personal.phone = "Test", "Candidate", "candidate@example.com", "+212600000000"
    p.links.linkedin = "https://www.linkedin.com/in/test-candidate"
    p.languages = [Language(language="English", level="fluent")]
    p.preferences.earliest_start_date = "2027-01-15"
    db.add(Profile(id=1, data=p.model_dump()))
    data = b"%PDF-1.4 e2e cv"
    (s.uploads_dir / "cv-e2e.pdf").write_bytes(data)
    db.add(Document(kind="cv", label="Main CV", filename="cv.pdf", stored_name="cv-e2e.pdf", mime="application/pdf", size=len(data),
                    sha256=hashlib.sha256(data).hexdigest(), is_default=True))
    db.flush()
    companies, jobs = {}, []
    for i, (cname, prov, tok, title, loc, html) in enumerate(JOBS):
        c = companies.get(tok)
        if c is None:
            c = companies[tok] = Company(name=cname, provider=prov, board_token=tok, last_status="ok: fixture")
            db.add(c)
            db.flush()
        from app.normalize import html_to_text
        text = html_to_text(html)
        pl = parse_location(loc)
        j = Job(company_id=c.id, provider=prov, external_id=f"e{i}", title=title, canonical_url=f"https://jobs.example/{tok}/e{i}",
                apply_url=f"https://jobs.example/{tok}/e{i}/apply", source_url=f"https://jobs.example/{tok}/e{i}", location_raw=loc,
                country=pl["country"], region=pl["region"], remote_mode=pl["remote_mode"], remote_scope=pl["remote_scope"],
                description_text=text, summary=summarize_role(html, text), fingerprint=fingerprint(title, loc, text),
                role_family=role_family(title), stage="verified", is_active=True)
        j.company = c
        if "salary range" in text:
            j.salary_text, j.salary_min, j.salary_max, j.salary_currency = "$60,000 - $75,000", 60000, 75000, "USD"
        apply_analysis(j, p)
        db.add(j)
        jobs.append(j)
    db.commit()
    shot = png()
    for idx in (0, 8):  # two applications waiting for approval
        job = jobs[idx]
        app = prepare_application(db, job, use_ai=False)
        app.status, job.stage = "awaiting_approval", "awaiting_approval"
        app.fill_report = {"mode": "fill", "ok": True, "outcome": "filled", "revision": app.revision, "content_hash": app.content_hash,
                           "filled": [{"key": a["key"], "label": a["label"], "detail": "ok"} for a in app.answers if a.get("value")],
                           "unfilled": [], "unmapped_required": [], "blockers": {"captcha": False, "recaptcha_present": False},
                           "finished_at": "2026-11-11T10:00:00Z", "final_url": job.apply_url}
        name = f"e2e-{app.id}.png"
        (s.screenshots_dir / name).write_bytes(shot)
        db.add(Screenshot(application_id=app.id, revision=app.revision, kind="filled", stored_name=name))
        emit(db, "form.filled", f"Form filled and waiting for your approval: {job.company.name} — {job.title}.", job_id=job.id, application_id=app.id)
        notify(db, "awaiting_approval", f"Review & approve: {job.title}", job.company.name, dedupe_key=f"approve:{app.id}", job_id=job.id, application_id=app.id)
    emit(db, "discovery.completed", "Search finished: 10 new, 0 updated, 0 closed.")
    db.commit()
    db.close()


if __name__ == "__main__":
    seed()
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8791, log_level="warning")
