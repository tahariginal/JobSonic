import pytest
from sqlalchemy import select

from app import pipeline, workflow
from app.models import Application, ApprovalEvent, MaterialVersion, Task
from app.preparation import prepare_application


def prepared(db, job_factory, cv, **kw):
    job = job_factory(**kw)
    app = prepare_application(db, job, use_ai=False)
    db.commit()
    return job, app


def to_awaiting(db, app):
    app.status = "awaiting_approval"
    app.job.stage = "awaiting_approval"
    app.fill_report = {"filled": [{"key": "name"}], "revision": app.revision, "content_hash": app.content_hash}
    db.commit()


def test_prepare_builds_truthful_material(db, job_factory, cv):
    job, app = prepared(db, job_factory, cv)
    assert app.status == "prepared" and job.stage == "preparing" and app.revision == 1 and len(app.content_hash) == 64
    by = {a["key"]: a for a in app.answers}
    assert by["name"]["value"] == "Test Candidate" and by["email"]["source"] == "profile"
    assert by["resume"]["value"]["document_id"] == cv.id
    assert "1337 School" in app.cover_letter and "work authorization" in app.cover_letter
    assert "bachelor" not in app.cover_letter.lower() and "degree" not in app.cover_letter.lower()
    assert db.query(MaterialVersion).count() == 1
    assert not pipeline.blocking_issues(app)


def test_missing_profile_data_blocks_instead_of_inventing(db, cv):
    from tests.conftest import make_job
    job = make_job(db)  # seed profile only: no name / email
    app = prepare_application(db, job, use_ai=False)
    db.commit()
    by = {a["key"]: a for a in app.answers}
    assert by["name"]["value"] is None and by["email"]["value"] is None
    assert len(pipeline.blocking_issues(app)) >= 2


def test_manual_stage_rules(db, job_factory):
    job = job_factory()
    pipeline.move_stage(db, job, "shortlisted")
    assert job.stage == "shortlisted"
    with pytest.raises(pipeline.PipelineError):
        pipeline.move_stage(db, job, "submitted")
    with pytest.raises(pipeline.PipelineError):
        pipeline.move_stage(db, job, "awaiting_approval")
    with pytest.raises(pipeline.PipelineError):
        pipeline.move_stage(db, job, "offer")
    job.stage = "submitted"
    with pytest.raises(pipeline.PipelineError) as e:
        pipeline.move_stage(db, job, "rejected")
    assert e.value.code == "confirm_required"
    pipeline.move_stage(db, job, "rejected", confirm=True)
    assert job.stage == "rejected"


def test_approval_requires_exact_current_version(db, job_factory, cv):
    job, app = prepared(db, job_factory, cv)
    with pytest.raises(pipeline.PipelineError):  # not awaiting approval yet
        pipeline.approve(db, app, app.revision, app.content_hash)
    to_awaiting(db, app)
    with pytest.raises(pipeline.PipelineError) as e:
        pipeline.approve(db, app, app.revision, "0" * 64)
    assert e.value.code == "stale"
    with pytest.raises(pipeline.PipelineError):
        pipeline.approve(db, app, app.revision + 1, app.content_hash)
    pipeline.approve(db, app, app.revision, app.content_hash)
    db.commit()
    assert app.status == "approved" and app.approved_hash == app.content_hash and app.submit_key
    assert db.query(Task).filter_by(type="submit_application").count() == 1


def test_any_change_after_approval_voids_it(db, job_factory, cv):
    job, app = prepared(db, job_factory, cv)
    to_awaiting(db, app)
    pipeline.approve(db, app, app.revision, app.content_hash)
    db.commit()
    key = app.submit_key
    app.cover_letter += "\nOne more line."
    assert pipeline.touch_content(db, app, "edit") is True
    db.commit()
    assert app.approved_revision is None and app.status == "prepared" and app.revision == 2 and job.stage == "preparing"
    assert db.query(ApprovalEvent).filter_by(action="invalidated").count() == 1
    assert pipeline.begin_submit(db, app.id, key) is None  # the old approval can no longer submit


def test_tampering_detected_even_without_touch(db, job_factory, cv):
    job, app = prepared(db, job_factory, cv)
    to_awaiting(db, app)
    pipeline.approve(db, app, app.revision, app.content_hash)
    answers = [dict(a) for a in app.answers]
    answers[0]["value"] = "Somebody Else"
    app.answers = answers
    db.commit()
    assert pipeline.begin_submit(db, app.id, app.submit_key) is None


def test_submit_gate_is_single_use(db, job_factory, cv):
    job, app = prepared(db, job_factory, cv)
    to_awaiting(db, app)
    pipeline.approve(db, app, app.revision, app.content_hash)
    db.commit()
    key = app.submit_key
    assert pipeline.begin_submit(db, app.id, "wrong-key") is None
    assert pipeline.begin_submit(db, app.id, key) is not None
    assert app.status == "submitting"
    assert pipeline.begin_submit(db, app.id, key) is None


def _approved(db, job_factory, cv, monkeypatch):
    monkeypatch.setattr(workflow, "verify_job", lambda db, job: True)
    job, app = prepared(db, job_factory, cv)
    to_awaiting(db, app)
    pipeline.approve(db, app, app.revision, app.content_hash)
    db.commit()
    return job, app


def test_duplicate_submission_is_prevented(db, job_factory, cv, monkeypatch):
    job, app = _approved(db, job_factory, cv, monkeypatch)
    calls = []

    def runner(db_, app_, mode, **kw):
        calls.append(mode)
        return {"outcome": "submitted", "ok": True, "final_url": "https://x/thanks", "confirmation_text": "Thank you for applying"}

    r1 = workflow.submit_application(db, app.id, app.submit_key, runner=runner)
    r2 = workflow.submit_application(db, app.id, app.submit_key, runner=runner)
    assert r1["ok"] is True and r2["ok"] is False and calls == ["submit"]
    assert app.status == "submitted" and job.stage == "submitted" and app.submitted_via == "agent"
    assert app.confirmation["confirmation_text"] == "Thank you for applying"
    with pytest.raises(pipeline.PipelineError):
        pipeline.touch_content(db, app, "late edit")


def test_browser_crash_before_send_requires_new_approval(db, job_factory, cv, monkeypatch):
    job, app = _approved(db, job_factory, cv, monkeypatch)

    def boom(*a, **k):
        raise RuntimeError("browser crashed")

    key = app.submit_key
    out = workflow.submit_application(db, app.id, key, runner=boom)
    assert out["ok"] is False and app.status == "failed" and app.approved_revision is None and app.submitted_at is None
    assert workflow.submit_application(db, app.id, key, runner=lambda *a, **k: {"outcome": "submitted"})["ok"] is False


def test_unknown_outcome_is_never_retried(db, job_factory, cv, monkeypatch):
    job, app = _approved(db, job_factory, cv, monkeypatch)
    key = app.submit_key
    workflow.submit_application(db, app.id, key, runner=lambda *a, **k: {"outcome": "uncertain", "error": "no confirmation", "clicked_at": "t"})
    assert app.status == "submit_uncertain"
    calls = []
    workflow.submit_application(db, app.id, key, runner=lambda *a, **k: calls.append(1) or {"outcome": "submitted"})
    assert calls == [] and app.status == "submit_uncertain"


def test_restart_mid_submit_becomes_uncertain(db, job_factory, cv, monkeypatch):
    job, app = _approved(db, job_factory, cv, monkeypatch)
    assert pipeline.begin_submit(db, app.id, app.submit_key) is not None  # worker died right here
    from app.worker import recover
    t = db.scalar(select(Task).where(Task.type == "submit_application"))
    t.status = "running"
    db.commit()
    recover(db)
    db.expire_all()
    app = db.get(Application, app.id)
    assert app.status == "submit_uncertain"
    assert db.get(Task, t.id).status == "failed"  # never re-queued


def test_closed_vacancy_is_not_submitted(db, job_factory, cv, monkeypatch):
    job, app = _approved(db, job_factory, cv, monkeypatch)
    monkeypatch.setattr(workflow, "verify_job", lambda db, job: False)
    calls = []
    out = workflow.submit_application(db, app.id, app.submit_key, runner=lambda *a, **k: calls.append(1))
    assert out["ok"] is False and calls == [] and app.status == "failed"


def test_reject_and_request_changes(db, job_factory, cv):
    job, app = prepared(db, job_factory, cv)
    to_awaiting(db, app)
    pipeline.request_changes(db, app, "shorter letter")
    assert app.status == "changes_requested" and job.stage == "preparing"
    to_awaiting(db, app)
    pipeline.reject(db, app, "not for me")
    assert app.status == "declined" and job.stage == "archived"


def test_fill_workflow_merges_discovered_questions(db, job_factory, cv, monkeypatch):
    monkeypatch.setattr(workflow, "verify_job", lambda db, job: True)
    job, app = prepared(db, job_factory, cv)
    rev = app.revision
    state = {"n": 0}

    def runner(db_, app_, mode, **kw):
        state["n"] += 1
        assert mode == "fill"
        disc = [{"key": "q_sponsor", "label": "Will you require visa sponsorship?", "type": "select", "required": True, "options": ["Yes", "No"]},
                {"key": "q_custom", "label": "What is your favourite sorting algorithm?", "type": "textarea", "required": True, "options": []}] if state["n"] == 1 else []
        missing = [{"label": "What is your favourite sorting algorithm?", "type": "textarea", "reason": "no answer prepared"}]
        return {"ok": True, "outcome": "filled", "filled": [{"key": "name"}], "discovered": disc, "unmapped_required": missing,
                "revision": app_.revision, "content_hash": app_.content_hash}

    out = workflow.fill_application(db, app.id, runner=runner)
    by = {a["key"]: a for a in app.answers}
    assert by["q_sponsor"]["value"] == "Yes" and by["q_sponsor"]["source"] == "profile"  # truthful: needs sponsorship in Germany
    assert by["q_custom"]["value"] is None  # never invented
    assert state["n"] == 2 and app.revision == rev + 1
    assert out["ok"] is False and app.status == "prepared" and pipeline.blocking_issues(app)
    assert job.stage == "preparing"


def test_fill_workflow_success_queues_for_approval(db, job_factory, cv, monkeypatch):
    monkeypatch.setattr(workflow, "verify_job", lambda db, job: True)
    job, app = prepared(db, job_factory, cv)
    out = workflow.fill_application(db, app.id, runner=lambda db_, a, mode, **kw: {
        "ok": True, "outcome": "filled", "filled": [{"key": "name"}], "discovered": [], "unmapped_required": [],
        "revision": a.revision, "content_hash": a.content_hash})
    assert out["ok"] and app.status == "awaiting_approval" and job.stage == "awaiting_approval"


def test_captcha_goes_to_manual(db, job_factory, cv, monkeypatch):
    monkeypatch.setattr(workflow, "verify_job", lambda db, job: True)
    job, app = prepared(db, job_factory, cv)
    workflow.fill_application(db, app.id, runner=lambda *a, **k: {"ok": False, "needs_manual": True, "error": "human check", "outcome": "failed_before_send"})
    assert app.status == "needs_manual"


def test_field_recognition_on_real_world_labels(db, profile, job_factory):
    from app.preparation import classify_field, resolve_answer
    assert classify_field("Country") == "country" and classify_field("Location (City)") == "location"
    assert classify_field("Are you open to relocation?") == "relocation"
    assert classify_field("Will you now or in the future require sponsorship for employment visa status?") == "sponsorship"
    assert classify_field("Are you legally authorized to work in the country in which you are applying?") == "work_auth"
    assert classify_field("Degree") == "degree" and classify_field("School") == "school"
    job = job_factory()
    ans = lambda label, **kw: resolve_answer({"key": "k", "label": label, "type": kw.get("type", "text"), "required": True, "options": kw.get("options", [])}, job, profile, "", None)  # noqa: E731
    assert ans("Country")["value"] == "Morocco"
    assert ans("Degree", options=["Bachelor's Degree", "Master's Degree", "High School"])["value"] is None  # never mapped onto a degree
    assert ans("Are you legally authorized to work in the country in which you are applying?", options=["Yes", "No"])["value"] == "No"
    assert ans("Gender", options=["Male", "Female", "Decline To Self Identify"])["value"] == "Decline To Self Identify"
    assert ans("What is your favourite database and why?")["value"] is None
