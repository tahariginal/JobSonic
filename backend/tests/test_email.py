from datetime import datetime

import httpx
import pytest

from app import emailing
from app.db import utcnow
from app.models import Application, EmailAccount, EmailMessage, Notification
from app.preparation import prepare_application


@pytest.mark.parametrize("subject,snippet,cat", [
    ("Thank you for applying to Acme", "We have received your application and will review it.", "confirmation"),
    ("Your application to Acme", "Unfortunately, we have decided to move forward with other candidates.", "rejection"),
    ("Interview invitation - Acme", "We would like to schedule a call. Please share your availability.", "interview"),
    ("Acme offer", "We are pleased to offer you the position of Junior Engineer.", "offer"),
    ("Next steps", "Please send your transcript and a copy of your passport.", "documents"),
    ("Weekly newsletter", "Ten tips for productivity", "other"),
    ("Thank you for applying", "Thank you for your interest. We regret to inform you that we will not be moving forward.", "rejection"),
])
def test_classification(subject, snippet, cat):
    assert emailing.classify(subject, snippet)[0] == cat


def test_weak_signals_have_low_confidence():
    cat, conf = emailing.classify("Update", "Unfortunately our office is closed on Monday.")
    assert cat == "rejection" and conf < 0.85


@pytest.fixture
def submitted(db, job_factory, cv):
    job = job_factory(company_name="Acme", title="Junior Backend Engineer")
    app = prepare_application(db, job, use_ai=False)
    app.status, app.submitted_at, job.stage = "submitted", utcnow(), "submitted"
    other = job_factory(company_name="Globex", token="globex", external_id="g1", title="Graduate Software Engineer")
    app2 = prepare_application(db, other, use_ai=False)
    app2.status, app2.submitted_at, other.stage = "submitted", utcnow(), "submitted"
    db.commit()
    return app, app2


def ingest(db, i, frm, subject, snippet, thread=""):
    m = emailing.ingest_message(db, gmail_id=f"m{i}", thread_id=thread or f"t{i}", from_addr=frm, subject=subject, snippet=snippet, received_at=datetime(2026, 11, 2))
    db.commit()
    return m


def test_matching_uses_sender_company_and_role(db, submitted):
    app, app2 = submitted
    m = ingest(db, 1, "Acme Recruiting <no-reply@greenhouse.io>", "Thank you for applying to Acme", "We received your application for Junior Backend Engineer.")
    assert m.application_id == app.id and m.match_confidence >= 0.9 and "role title quoted" in m.match_reason
    m2 = ingest(db, 2, "Jane <jane@globex.com>", "Hello", "Quick question about your application.")
    assert m2.application_id == app2.id and m2.category == "recruiter_reply"
    assert ingest(db, 3, "News <news@unrelated.io>", "Weekly newsletter", "Ten tips") is None
    assert ingest(db, 1, "dup", "dup", "dup") is None  # idempotent on gmail id


def test_clear_interview_moves_pipeline_and_notifies(db, submitted):
    app, _ = submitted
    m = ingest(db, 1, "Acme Talent <talent@acme.com>", "Interview invitation - Junior Backend Engineer", "We would like to schedule a call with you.")
    assert m.applied_to_pipeline and app.job.stage == "interview"
    assert db.query(Notification).filter_by(kind="interview").count() == 1


def test_ambiguous_email_never_marks_rejected(db, submitted):
    app, _ = submitted
    m = ingest(db, 1, "Acme <hr@acme.com>", "Update", "Unfortunately our office is closed on Monday, we will reply later.")
    assert m.category == "rejection" and m.confidence < 0.85
    assert app.job.stage == "submitted" and m.applied_to_pipeline is False
    n = db.query(Notification).filter_by(kind="rejection").one()
    assert "not changed automatically" in n.body


def test_clear_rejection_is_applied(db, submitted):
    app, _ = submitted
    ingest(db, 1, "Acme <no-reply@acme.com>", "Your application for Junior Backend Engineer", "We regret to inform you that we will not be moving forward.")
    assert app.job.stage == "rejected"


def test_thread_inheritance(db, submitted):
    app, _ = submitted
    ingest(db, 1, "Acme Talent <talent@acme.com>", "Junior Backend Engineer", "Hello from Acme", thread="T")
    m = ingest(db, 2, "Sam <sam@gmail.com>", "Re: next steps", "Could we schedule a call for Tuesday?", thread="T")
    assert m is not None and m.application_id == app.id and m.match_reason.startswith("same conversation")


def test_oauth_flow_and_sync_with_mocked_google(db, submitted):
    app, _ = submitted
    with pytest.raises(ValueError):
        emailing.auth_start_url(db)
    emailing.set_oauth_config(db, "cid.apps.googleusercontent.com", "secret")
    db.commit()
    url = emailing.auth_start_url(db)
    assert "gmail.readonly" in url and "redirect_uri=https%3A%2F%2Fsonic.test%2Fapi%2Femail%2Foauth%2Fcallback" in url
    assert "gmail.send" not in url and "gmail.modify" not in url
    state = url.split("state=")[1]

    def handler(req: httpx.Request) -> httpx.Response:
        u = str(req.url)
        if u.startswith(emailing.TOKEN_URL):
            body = req.content.decode()
            if "authorization_code" in body:
                return httpx.Response(200, json={"access_token": "at", "refresh_token": "rt-secret", "scope": emailing.SCOPE})
            return httpx.Response(200, json={"access_token": "at2"})
        if u.endswith("/profile"):
            return httpx.Response(200, json={"emailAddress": "me@example.com"})
        if "/messages?" in u:
            return httpx.Response(200, json={"messages": [{"id": "g1"}, {"id": "g2"}]})
        if "/messages/g1" in u:
            return httpx.Response(200, json={"id": "g1", "threadId": "t1", "snippet": "We would like to schedule a call with you.",
                                             "payload": {"headers": [{"name": "From", "value": "Acme Talent <talent@acme.com>"}, {"name": "Subject", "value": "Interview invitation"},
                                                                     {"name": "Date", "value": "Mon, 02 Nov 2026 10:00:00 +0000"}]}})
        return httpx.Response(200, json={"id": "g2", "threadId": "t2", "snippet": "sale", "payload": {"headers": [{"name": "From", "value": "shop@x.com"}, {"name": "Subject", "value": "Deals"}]}})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(ValueError):
        emailing.complete_oauth(db, "code", "wrong-state", http=http)
    emailing.auth_start_url(db)
    state = emailing.get_setting(db, "google_oauth_state")["state"]
    acct = emailing.complete_oauth(db, "code", state, http=http)
    assert acct.email == "me@example.com" and "rt-secret" not in acct.encrypted_token  # stored encrypted
    with pytest.raises(ValueError):
        emailing.complete_oauth(db, "code", state, http=http)  # state is single-use
    stats = emailing.sync_account(db, acct, http=http)
    assert stats == {"checked": 2, "stored": 1, "matched": 1}
    assert app.job.stage == "interview" and db.query(EmailMessage).count() == 1
    assert emailing.sync_account(db, acct, http=http)["stored"] == 0
