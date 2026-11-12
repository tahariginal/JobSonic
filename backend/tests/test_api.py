import io

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import AuditLog, Company, Task


@pytest.fixture
def anon():
    return TestClient(app)


@pytest.fixture
def client(user):
    c = TestClient(app)
    r = c.post("/api/auth/login", json={"username": "admin", "password": "correct horse battery"})
    assert r.status_code == 200
    c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    return c


PROTECTED = ["/api/profile", "/api/jobs", "/api/pipeline", "/api/overview", "/api/analytics", "/api/events", "/api/approvals",
             "/api/documents", "/api/settings", "/api/companies", "/api/notifications", "/api/emails", "/api/audit", "/api/tasks",
             "/api/applications", "/api/documents/1/download", "/api/screenshots/1", "/api/email/status"]


@pytest.mark.parametrize("path", PROTECTED)
def test_everything_requires_authentication(anon, path):
    assert anon.get(path).status_code == 401


def test_health_is_public_and_minimal(anon):
    r = anon.get("/api/health")
    assert r.status_code == 200 and set(r.json()) == {"status", "db", "time"}


def test_login_failure_and_rate_limit(anon, user, db):
    for _ in range(6):
        assert anon.post("/api/auth/login", json={"username": "admin", "password": "nope"}).status_code == 401
    assert anon.post("/api/auth/login", json={"username": "admin", "password": "correct horse battery"}).status_code == 429
    assert db.query(AuditLog).filter_by(action="auth.login_failed").count() == 6


def test_session_cookie_flags_and_logout(user):
    c = TestClient(app)
    r = c.post("/api/auth/login", json={"username": "admin", "password": "correct horse battery"})
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    assert c.get("/api/auth/me").status_code == 200
    c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    assert c.post("/api/auth/logout").status_code == 200
    assert c.get("/api/profile").status_code == 401


def test_csrf_required_on_writes(client):
    token = client.headers.pop("X-CSRF-Token")
    assert client.put("/api/settings", json={}).status_code == 403
    client.headers["X-CSRF-Token"] = "wrong"
    assert client.post("/api/discovery/run", json={}).status_code == 403
    client.headers["X-CSRF-Token"] = token
    assert client.put("/api/settings", json={}).status_code == 200


def test_security_headers(client):
    h = client.get("/api/overview").headers
    assert h["x-frame-options"] == "DENY" and h["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in h["content-security-policy"] and h["cache-control"] == "no-store"


def test_profile_roundtrip_and_seed_truthfulness(client, db):
    p = client.get("/api/profile").json()
    d = p["data"]
    assert d["personal"]["citizenship"] == "Moroccan" and d["work_authorization"]["authorized_countries"] == ["Morocco"]
    assert d["personal"]["first_name"] == "" and "Full name" in p["gaps"]
    assert all("bachelor" not in (e["credential"] + e["program"]).lower() for e in d["education"])
    assert d["languages"] == []  # never invented
    d["personal"]["first_name"], d["personal"]["last_name"] = "A", "B"
    d["standard_answers"] = [{"question": "How did you hear about us?", "answer": "Company careers page"}]
    r = client.put("/api/profile", json=d)
    assert r.status_code == 200 and "Full name" not in r.json()["gaps"]
    assert client.get("/api/profile").json()["data"]["standard_answers"][0]["answer"] == "Company careers page"
    assert db.query(Task).filter_by(type="reanalyze").count() == 1


def test_document_upload_validation(client):
    ok = client.post("/api/documents", files={"file": ("cv.pdf", io.BytesIO(b"%PDF-1.4 hello"), "application/pdf")}, data={"kind": "cv", "label": "Main"})
    assert ok.status_code == 200 and ok.json()["is_default"] is True
    assert client.post("/api/documents", files={"file": ("x.exe", io.BytesIO(b"MZ"), "application/octet-stream")}).status_code == 400
    assert client.post("/api/documents", files={"file": ("fake.pdf", io.BytesIO(b"<html>"), "application/pdf")}).status_code == 400
    assert client.post("/api/documents", files={"file": ("big.pdf", io.BytesIO(b"%PDF" + b"0" * (5 * 1024 * 1024 + 5)), "application/pdf")}).status_code == 413
    trav = client.post("/api/documents", files={"file": ("../../etc/passwd.pdf", io.BytesIO(b"%PDF-1"), "application/pdf")})
    assert trav.status_code == 200 and "/" not in trav.json()["filename"]
    doc_id = ok.json()["id"]
    assert client.get(f"/api/documents/{doc_id}/download").content == b"%PDF-1.4 hello"
    assert client.delete(f"/api/documents/{doc_id}").status_code == 200
    assert client.get(f"/api/documents/{doc_id}/download").status_code == 404


def test_job_listing_filters_and_detail(client, job_factory):
    a = job_factory(title="Junior Backend Engineer", external_id="a", description="0-2 years of experience. C++ APIs. Visa sponsorship is available.")
    job_factory(title="Senior Backend Engineer", external_id="b", country="France", location="Paris, France")
    job_factory(title="Software Engineer", external_id="c", country="Japan", location="Tokyo, Japan", description="We are unable to sponsor visas.")
    all_ = client.get("/api/jobs").json()
    assert all_["total"] == 3 and all_["items"][0]["id"] == a.id  # best fit first
    assert client.get("/api/jobs", params={"eligibility": "eligible"}).json()["total"] == 1
    assert client.get("/api/jobs", params={"visa": "confirmed"}).json()["total"] == 2
    assert client.get("/api/jobs", params={"country": "Japan"}).json()["items"][0]["visa_status"] == "not_supported"
    assert client.get("/api/jobs", params={"level": "senior"}).json()["total"] == 1
    assert client.get("/api/jobs", params={"min_stars": 4}).json()["total"] == 1
    assert client.get("/api/jobs", params={"q": "tokyo"}).json()["total"] == 1
    assert client.get("/api/jobs", params={"country": "Germany|France"}).json()["total"] == 2
    rej = client.get("/api/jobs", params={"eligibility": "rejected"}).json()["items"]
    assert all(r["rejection_reasons"] for r in rej)
    d = client.get(f"/api/jobs/{a.id}").json()
    assert d["visa_evidence"][0]["quote"] and d["visa_evidence"][0]["source_url"] and d["eligibility_reasons"]
    assert d["is_new"] is True and client.get(f"/api/jobs/{a.id}").json()["is_new"] is False  # opening marks it seen
    f = client.get("/api/jobs/facets").json()
    assert {x["value"] for x in f["country"]} == {"Germany", "France", "Japan"}
    assert client.patch(f"/api/jobs/{a.id}", json={"saved": True}).json()["saved"] is True
    assert client.get("/api/jobs", params={"saved": True}).json()["total"] == 1


def test_stage_endpoint_enforces_workflow(client, job_factory, db):
    j = job_factory()
    assert client.post(f"/api/jobs/{j.id}/stage", json={"to": "shortlisted"}).json()["stage"] == "shortlisted"
    r = client.post(f"/api/jobs/{j.id}/stage", json={"to": "submitted"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "workflow"
    assert client.post(f"/api/jobs/{j.id}/stage", json={"to": "preparing"}).status_code == 200
    assert db.query(Task).filter_by(type="prepare_application").count() == 1
    board = client.get("/api/pipeline").json()
    assert [c["id"] for c in board["columns"]["preparing"]] == [j.id] and board["counts"]["preparing"] == 1


def test_application_review_edit_and_approval_over_http(client, job_factory, cv, db):
    from app.preparation import prepare_application
    j = job_factory()
    a = prepare_application(db, j, use_ai=False)
    a.status, j.stage = "awaiting_approval", "awaiting_approval"
    db.commit()
    d = client.get(f"/api/applications/{a.id}").json()
    assert d["status"] == "awaiting_approval" and d["answers"] and d["cover_letter"] and d["cv"]["id"] == cv.id
    assert client.get("/api/approvals").json()["awaiting"][0]["id"] == a.id
    stale = client.post(f"/api/applications/{a.id}/approve", json={"revision": d["revision"], "content_hash": "f" * 64})
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "stale"
    ok = client.post(f"/api/applications/{a.id}/approve", json={"revision": d["revision"], "content_hash": d["content_hash"]})
    assert ok.status_code == 200 and ok.json()["status"] == "approved" and ok.json()["approvals"][0]["action"] == "approve"
    # editing after approval voids it and needs a new review
    e = client.put(f"/api/applications/{a.id}", json={"cover_letter": d["cover_letter"] + "\nPS."})
    assert e.status_code == 200 and e.json()["status"] == "prepared" and e.json()["approved_revision"] is None and e.json()["revision"] == d["revision"] + 1
    assert [x["action"] for x in e.json()["approvals"]][:1] == ["invalidated"]
    again = client.post(f"/api/applications/{a.id}/approve", json={"revision": d["revision"], "content_hash": d["content_hash"]})
    assert again.status_code == 409


def test_ineligible_job_cannot_be_prepared_without_override(client, job_factory):
    j = job_factory(title="Senior Backend Engineer")
    assert client.post(f"/api/jobs/{j.id}/prepare").json()["detail"]["code"] == "ineligible"
    client.patch(f"/api/jobs/{j.id}", json={"eligibility": "needs_review"})
    assert client.post(f"/api/jobs/{j.id}/prepare").status_code == 200


def test_settings_validation_and_secrets_never_returned(client):
    r = client.put("/api/settings", json={"schedule": {"discovery_interval_hours": 6, "unknown_key": 1}, "ai": {"daily_call_budget": 5}})
    assert r.status_code == 200 and r.json()["schedule"]["discovery_interval_hours"] == 6 and "unknown_key" not in r.json()["schedule"]
    assert client.put("/api/settings", json={"ai": {"daily_call_budget": "lots"}}).status_code == 400
    assert client.put("/api/settings/telegram", json={"bot_token": "bad", "chat_id": "1"}).status_code == 422
    assert client.put("/api/settings/google-oauth", json={"client_id": "1234567890-abc.apps.googleusercontent.com", "client_secret": "GOCSPX-supersecret"}).status_code == 200
    body = client.get("/api/settings").text
    assert "GOCSPX-supersecret" not in body and '"configured":true' in body.replace(" ", "")
    s = client.get("/api/settings").json()
    assert s["ai_status"]["available"] is False and s["ai"]["enabled"] is False  # AI is off by default


def test_overview_and_analytics_report_only_real_data(client, job_factory):
    o = client.get("/api/overview").json()
    assert o["metrics"]["jobs_discovered"] == 0 and o["metrics"]["response_rate"] is None and o["recent_activity"] == []
    job_factory()
    o = client.get("/api/overview").json()
    assert o["metrics"]["jobs_discovered"] == 1 and o["metrics"]["submitted"] == 0 and o["metrics"]["response_rate"] is None
    a = client.get("/api/analytics").json()
    assert a["interview_conversion"] is None and a["applications_over_time"] == [] and a["ai"]["usage"]["all_time"]["calls"] == 0
    assert a["visa_distribution"][0]["status"] == "confirmed"


def test_unverifiable_source_is_refused(client, monkeypatch, db):
    from app import main
    from app.sources import SourceError

    class Fake:
        def fetch(self, c, t):
            raise SourceError("board not found")

    monkeypatch.setitem(main.ADAPTERS, "lever", Fake())
    r = client.post("/api/companies", json={"provider": "lever", "board_token": "does-not-exist"})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "unverified"
    assert db.query(Company).count() == 0
    assert client.post("/api/companies", json={"provider": "lever", "board_token": "../etc"}).status_code == 422


def test_manual_discovery_run_is_queued_once(client, db):
    assert client.post("/api/discovery/run", json={}).status_code == 200
    assert client.post("/api/discovery/run", json={}).status_code == 409
    assert db.query(Task).filter_by(type="discovery").count() == 1
