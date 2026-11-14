"""Real-browser tests of the form agent against local fixture forms.

No real employer site is contacted and nothing is ever submitted outside 127.0.0.1.
"""
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import pytest

from app import pipeline, preparation, workflow
from app.automation import match_fields, run_form
from app.config import get_settings
from app.models import Application, Screenshot
from app.preparation import prepare_application

FORMS = Path(__file__).parent / "fixtures" / "forms"
THANKS = b"<html><body><h1>Thank you for applying!</h1><p>Your application has been received.</p></body></html>"


class Handler(BaseHTTPRequestHandler):
    posts: list = []

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="text/html"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/gone":
            return self._send(404, b"<html><body>Not found</body></html>")
        if path.startswith("/recaptcha"):
            return self._send(200, b"<html><body>Select all squares with traffic lights</body></html>")
        name = path.strip("/").split("/")[0]
        f = FORMS / f"{name}.html"
        if not f.is_file():
            return self._send(404, b"nope")
        mode = (urlparse(self.path).query or "mode=ok").split("=")[-1]
        self._send(200, f.read_bytes().replace(b"__MODE__", mode.encode()))

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        Handler.posts.append({"path": self.path, "body": body})
        if "mode=silent" in self.path:
            return self._send(200, b"<html><body><p>Processing</p></body></html>")
        if "mode=invalid" in self.path:
            self.send_response(204)
            self.end_headers()
            return
        self._send(200, THANKS)


@pytest.fixture(scope="module")
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    Handler.posts.clear()
    monkeypatch.setattr(workflow, "verify_job", lambda db, job: True)


GH_SCHEMA = [
    {"key": "first_name", "label": "First Name", "type": "text", "required": True, "options": [], "help": ""},
    {"key": "last_name", "label": "Last Name", "type": "text", "required": True, "options": [], "help": ""},
    {"key": "email", "label": "Email", "type": "text", "required": True, "options": [], "help": ""},
    {"key": "phone", "label": "Phone", "type": "text", "required": False, "options": [], "help": ""},
    {"key": "resume", "label": "Resume/CV", "type": "file", "required": True, "options": [], "help": ""},
    {"key": "question_101", "label": "LinkedIn Profile", "type": "text", "required": False, "options": [], "help": ""},
    {"key": "question_102", "label": "Website", "type": "text", "required": False, "options": [], "help": ""},
    {"key": "question_103", "label": "Why do you want to work at Globex?", "type": "textarea", "required": True, "options": [], "help": ""},
    {"key": "question_104", "label": "Do you require visa sponsorship?", "type": "select", "required": True, "options": ["Yes", "No"], "help": ""},
    {"key": "__demographic", "label": "Voluntary demographic questions", "type": "info", "required": False, "options": [], "help": "left unanswered"},
]


def make_app(db, job_factory, server, form, provider="lever", **kw):
    job = job_factory(provider=provider, **kw)
    app = prepare_application(db, job, use_ai=False)
    schema = dict(app.form_schema)
    schema["form_url"] = f"{server}/{form}"
    app.form_schema = schema
    db.commit()
    return job, app


def body_text(post):
    return post["body"].decode("utf-8", "replace")


def test_lever_fill_never_submits_and_answers_truthfully(db, job_factory, cv, server):
    job, app = make_app(db, job_factory, server, "lever")
    out = workflow.fill_application(db, app.id)
    assert Handler.posts == []  # fill mode must never send anything
    rep = app.fill_report
    filled = {f["key"]: f["detail"] for f in rep["filled"]}
    assert filled["name"] == "ok" and filled["email"] == "ok" and filled["resume"] == "cv-test.pdf"
    assert filled["urls[GitHub]"] == "ok" and filled["urls[LinkedIn]"] == "ok"
    by = {a["key"]: a for a in app.answers}
    # questions found only on the live page were merged in and answered from the profile
    assert by["cards[a1][field0]"]["value"] == "Yes" and by["cards[a1][field0]"]["discovered"] is True
    assert by["cards[a1][field1]"]["value"] == "No"
    assert filled["cards[a1][field0]"] == "Yes" and filled["cards[a1][field1]"] == "No"
    assert out["ok"] and app.status == "awaiting_approval" and job.stage == "awaiting_approval"
    shots = db.query(Screenshot).filter_by(application_id=app.id).all()
    assert shots and (get_settings().screenshots_dir / shots[-1].stored_name).stat().st_size > 2000
    assert rep["revision"] == app.revision and rep["content_hash"] == app.content_hash


def test_lever_approved_submit_sends_exactly_once(db, job_factory, cv, server):
    job, app = make_app(db, job_factory, server, "lever")
    workflow.fill_application(db, app.id)
    pipeline.approve(db, app, app.revision, app.content_hash)
    db.commit()
    key = app.submit_key
    r1 = workflow.submit_application(db, app.id, key)
    r2 = workflow.submit_application(db, app.id, key)
    assert r1["ok"] is True and r2["ok"] is False
    assert len(Handler.posts) == 1
    sent = body_text(Handler.posts[0])
    assert "Test Candidate" in sent and "candidate@example.com" in sent and "%PDF-1.4 test cv" in sent
    assert 'name="cards[a1][field0]"\r\n\r\nYes' in sent
    assert app.status == "submitted" and job.stage == "submitted" and "thank you for applying" in app.confirmation["confirmation_text"].lower()
    assert db.query(Screenshot).filter_by(application_id=app.id, kind="confirmation").count() == 1


def test_submit_without_approval_is_impossible(db, job_factory, cv, server):
    job, app = make_app(db, job_factory, server, "lever")
    workflow.fill_application(db, app.id)
    assert workflow.submit_application(db, app.id, "guessed-key")["ok"] is False
    assert workflow.submit_application(db, app.id, "")["ok"] is False
    assert Handler.posts == [] and app.status == "awaiting_approval"


def test_edit_after_approval_blocks_submit(db, job_factory, cv, server):
    job, app = make_app(db, job_factory, server, "lever")
    workflow.fill_application(db, app.id)
    pipeline.approve(db, app, app.revision, app.content_hash)
    db.commit()
    key = app.submit_key
    answers = [dict(a) for a in app.answers]
    next(a for a in answers if a["key"] == "phone")["value"] = "+212611111111"
    app.answers = answers
    pipeline.touch_content(db, app, "phone changed")
    db.commit()
    assert workflow.submit_application(db, app.id, key)["ok"] is False
    assert Handler.posts == []


def test_greenhouse_fills_motivation_and_discovered_start_date_without_ai(db, job_factory, cv, server, monkeypatch):
    from app.models import Profile
    profile = preparation.load_profile(db)
    profile.preferences.earliest_start_date = "2027-01-07"
    db.get(Profile, 1).data = profile.model_dump()
    db.commit()
    monkeypatch.setattr(preparation, "_greenhouse_schema", lambda job, client: [dict(f) for f in GH_SCHEMA])
    job, app = make_app(db, job_factory, server, "greenhouse", provider="greenhouse", company_name="Globex", token="globex", title="Graduate Software Engineer")
    by = {a["key"]: a for a in app.answers}
    assert by["question_103"]["value"] == profile.preferences.motivation_answer
    assert by["question_104"]["value"] == "Yes" and by["first_name"]["value"] == "Test"
    assert not pipeline.blocking_issues(app)
    out = workflow.fill_application(db, app.id)
    assert out["ok"] and app.status == "awaiting_approval" and Handler.posts == []
    by = {a["key"]: a for a in app.answers}
    assert by["start_date"]["value"] == "2027-01-07"
    assert {f["key"]: f["detail"] for f in app.fill_report["filled"]}["start_date"] == "ok"
    assert {f["key"]: f["detail"] for f in app.fill_report["filled"]}["question_103"] == "ok"

    # the user writes the answer -> fill -> everything placed, including the hidden file input and the <select>
    answers = [dict(a) for a in app.answers]
    next(a for a in answers if a["key"] == "question_103")["value"] = "I like the product and the engineering blog."
    next(a for a in answers if a["key"] == "question_103")["source"] = "manual"
    app.answers = answers
    app.issues = preparation.collect_issues(app, preparation.load_profile(db), cv)
    pipeline.touch_content(db, app, "answer added")
    db.commit()
    out = workflow.fill_application(db, app.id)
    filled = {f["key"]: f["detail"] for f in app.fill_report["filled"]}
    assert out["ok"], app.fill_report
    assert filled["resume"] == "cv-test.pdf" and filled["question_104"] == "Yes" and filled["question_103"] == "ok"
    assert filled["question_102"] == "ok"  # portfolio -> Website
    gender = next(a for a in app.answers if a["key"] == "gender")
    assert gender["value"] == "Decline To Self Identify"  # voluntary question: decline option only
    assert app.fill_report["blockers"]["recaptcha_present"] is True and app.fill_report["blockers"]["captcha"] is False

    pipeline.approve(db, app, app.revision, app.content_hash)
    db.commit()
    assert workflow.submit_application(db, app.id, app.submit_key)["ok"] is True
    sent = body_text(Handler.posts[0])
    assert len(Handler.posts) == 1 and "I like the product" in sent and 'name="question_104"\r\n\r\n1' in sent
    assert 'name="start_date"\r\n\r\n2027-01-07' in sent


def test_ashby_spa_consent_must_be_given_by_user(db, job_factory, cv, server):
    job, app = make_app(db, job_factory, server, "ashby", provider="ashby", company_name="Initech", token="initech", title="AI Agent Engineer")
    out = workflow.fill_application(db, app.id)
    by = {a["key"]: a for a in app.answers}
    assert by["q_reloc"]["value"] == "Yes" and by["q_li"]["value"].startswith("https://www.linkedin.com")
    assert by["q_privacy"]["value"] is None and "tick this yourself" in by["q_privacy"]["note"]
    assert out["ok"] is False and any("privacy" in i["text"].lower() for i in pipeline.blocking_issues(app))
    answers = [dict(a) for a in app.answers]
    next(a for a in answers if a["key"] == "q_privacy").update(value=True, source="manual")
    app.answers = answers
    pipeline.touch_content(db, app, "consent given")
    db.commit()
    out = workflow.fill_application(db, app.id)
    assert out["ok"], app.fill_report
    pipeline.approve(db, app, app.revision, app.content_hash)
    db.commit()
    assert workflow.submit_application(db, app.id, app.submit_key)["ok"] is True
    sent = body_text(Handler.posts[0])
    assert 'name="q_privacy"' in sent and 'name="q_reloc"\r\n\r\nYes' in sent


def test_no_confirmation_page_is_uncertain_and_not_retried(db, job_factory, cv, server):
    job, app = make_app(db, job_factory, server, "ashby?mode=silent", provider="ashby", company_name="Initech", token="initech", title="AI Agent Engineer")
    workflow.fill_application(db, app.id)
    answers = [dict(a) for a in app.answers]
    next(a for a in answers if a["key"] == "q_privacy").update(value=True, source="manual")
    app.answers = answers
    pipeline.touch_content(db, app, "consent")
    db.commit()
    workflow.fill_application(db, app.id)
    pipeline.approve(db, app, app.revision, app.content_hash)
    db.commit()
    key = app.submit_key
    out = workflow.submit_application(db, app.id, key)
    assert out["outcome"] == "uncertain" and app.status == "submit_uncertain" and len(Handler.posts) == 1
    assert workflow.submit_application(db, app.id, key)["ok"] is False and len(Handler.posts) == 1


def test_captcha_is_detected_not_bypassed(db, job_factory, cv, server):
    job, app = make_app(db, job_factory, server, "captcha")
    out = workflow.fill_application(db, app.id)
    assert out["ok"] is False and app.status == "needs_manual" and app.fill_report["blockers"]["captcha"] is True
    assert Handler.posts == []


def test_closed_posting_page(db, job_factory, cv, server):
    job, app = make_app(db, job_factory, server, "closed")
    res = run_form(db, app, "fill")
    assert res["closed"] is True and res["outcome"] == "failed_before_send"
    job2, app2 = make_app(db, job_factory, server, "gone", external_id="j2")
    assert run_form(db, app2, "fill")["closed"] is True


def test_real_submit_can_be_disabled_server_side(db, job_factory, cv, server, monkeypatch):
    job, app = make_app(db, job_factory, server, "lever")
    workflow.fill_application(db, app.id)
    pipeline.approve(db, app, app.revision, app.content_hash)
    db.commit()
    monkeypatch.setattr(get_settings(), "allow_real_submit", False)
    out = workflow.submit_application(db, app.id, app.submit_key)
    assert out["ok"] is False and Handler.posts == [] and app.status == "failed"


def test_field_matching_prefers_key_then_label_then_kind():
    answers = [{"key": "email", "label": "Email", "kind": "email"}, {"key": "x", "label": "LinkedIn Profile", "kind": "linkedin"},
               {"key": "y", "label": "Phone number", "kind": "phone"}]
    dom = [{"sid": "a", "name": "", "id": "email", "label": "E-mail address", "type": "text"},
           {"sid": "b", "name": "q9", "id": "", "label": "LinkedIn profile", "type": "text"},
           {"sid": "c", "name": "q3", "id": "", "label": "Mobile number", "type": "tel"},
           {"sid": "d", "name": "q4", "id": "", "label": "Favourite colour", "type": "text"}]
    m = match_fields(answers, dom)
    assert m["email"]["sid"] == "a" and m["x"]["sid"] == "b" and m["y"]["sid"] == "c" and len(m) == 3
