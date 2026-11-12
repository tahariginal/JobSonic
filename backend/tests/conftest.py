import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="sonic-test-")
os.environ.update({
    "SONIC_DATA_DIR": _TMP, "SONIC_ENV": "test", "SONIC_COOKIE_SECURE": "false", "SONIC_SECRET_KEY": "test-secret",
    "SONIC_ENCRYPTION_KEY": "x9bP0mW2m0u2W2Yc3m7mJq3r8yq0m0F4n9s8m1Zk1uE=", "SONIC_AI_MODE": "off",
    "SONIC_PUBLIC_BASE_URL": "https://sonic.test", "SONIC_FRONTEND_DIR": os.path.join(_TMP, "nofrontend"),
})

import pytest  # noqa: E402

from app import models  # noqa: E402,F401
from app.db import Base, SessionLocal, get_engine  # noqa: E402
from app.models import Company, Document, Job, Profile, User  # noqa: E402
from app.schemas import Language, seed_profile  # noqa: E402
from app.security import hash_password, limiter  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_db():
    eng = get_engine()
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    limiter.reset()
    yield


@pytest.fixture
def db():
    s = SessionLocal()
    yield s
    s.close()


@pytest.fixture
def profile(db):
    p = seed_profile()
    p.personal.first_name, p.personal.last_name = "Test", "Candidate"
    p.personal.email, p.personal.phone, p.personal.city = "candidate@example.com", "+212600000000", "Khouribga"
    p.links.linkedin = "https://www.linkedin.com/in/test-candidate"
    p.languages = [Language(language="English", level="fluent")]
    p.preferences.earliest_start_date = "2027-01-15"
    db.add(Profile(id=1, data=p.model_dump()))
    db.commit()
    return p


@pytest.fixture
def user(db):
    u = User(username="admin", password_hash=hash_password("correct horse battery"))
    db.add(u)
    db.commit()
    return u


@pytest.fixture
def cv(db):
    from app.config import get_settings
    data = b"%PDF-1.4 test cv"
    (get_settings().uploads_dir / "cv-test.pdf").write_bytes(data)
    import hashlib
    d = Document(kind="cv", label="Main CV", filename="cv.pdf", stored_name="cv-test.pdf", mime="application/pdf",
                 size=len(data), sha256=hashlib.sha256(data).hexdigest(), is_default=True)
    db.add(d)
    db.commit()
    return d


def make_job(db, *, provider="lever", title="Junior Backend Engineer", country="Germany", description="", token="acme",
             external_id="j1", company_name="Acme", **kw):
    from app.discovery import apply_analysis, load_profile
    from app.normalize import fingerprint, parse_location, role_family
    c = db.query(Company).filter_by(provider=provider, board_token=token).first()
    if c is None:
        c = Company(name=company_name, provider=provider, board_token=token)
        db.add(c)
        db.flush()
    loc = kw.pop("location", f"Berlin, {country}" if country == "Germany" else country)
    pl = parse_location(loc)
    j = Job(company_id=c.id, provider=provider, external_id=external_id, title=title,
            canonical_url=f"https://jobs.example/{token}/{external_id}", apply_url=f"https://jobs.example/{token}/{external_id}/apply",
            source_url=f"https://jobs.example/{token}/{external_id}", location_raw=loc, country=pl["country"], region=pl["region"],
            remote_mode=pl["remote_mode"], remote_scope=pl["remote_scope"],
            description_text=description or "Build APIs in Python. Visa sponsorship is available for this role.",
            fingerprint=fingerprint(title, loc, description), role_family=role_family(title), stage="verified", is_active=True, **kw)
    j.company = c
    apply_analysis(j, load_profile(db))
    db.add(j)
    db.commit()
    return j


@pytest.fixture
def job_factory(db, profile):
    return lambda **kw: make_job(db, **kw)
