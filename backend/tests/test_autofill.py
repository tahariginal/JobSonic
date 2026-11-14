"""Scheduled search-to-fill policy. All discovery and browser calls are local mocks."""
from datetime import timedelta

import pytest
from sqlalchemy import select

from app import worker, workflow
from app.core import enqueue, get_setting, set_setting
from app.db import utcnow
from app.models import Application, Job, Task


def enable(db, **overrides):
    cfg = get_setting(db, "automation")
    cfg.update(auto_fill_enabled=True, max_applications_per_cycle=20, include_other_matches=True)
    cfg.update(overrides)
    set_setting(db, "automation", cfg)
    if "auto_submit_enabled" in overrides:
        from app.discovery import load_profile
        from app.models import Profile
        profile = load_profile(db)
        profile.application_policy.require_final_approval = not cfg["auto_submit_enabled"]
        db.get(Profile, 1).data = profile.model_dump()
    db.commit()


def candidate(job_factory, external_id, **changes):
    job = job_factory(external_id=external_id)
    job.eligibility, job.visa_status, job.remote_mode = "eligible", "unverified", "onsite"
    job.last_verified_at = utcnow()
    for key, value in changes.items():
        setattr(job, key, value)
    return job


def test_highest_fit_first_with_freshness_limits_and_duplicate_protection(db, job_factory):
    enable(db, max_applications_per_cycle=3)
    since = utcnow() - timedelta(minutes=1)
    other = candidate(job_factory, "other", fit_score=99)
    remote = candidate(job_factory, "remote", remote_mode="remote", fit_score=80)
    visa = candidate(job_factory, "visa", visa_status="confirmed", fit_score=30)
    candidate(job_factory, "review", eligibility="needs_review", visa_status="confirmed", fit_score=100)
    candidate(job_factory, "rejected", eligibility="rejected", visa_status="confirmed", fit_score=100)
    candidate(job_factory, "closed", is_active=False, visa_status="confirmed", fit_score=100)
    candidate(job_factory, "archived", stage="archived", visa_status="confirmed", fit_score=100)
    candidate(job_factory, "stale", last_verified_at=since - timedelta(seconds=1), visa_status="confirmed", fit_score=100)
    candidate(job_factory, "overflow", fit_score=1)
    db.commit()
    assert worker.queue_auto_applications(db, verified_since=since) == 3
    tasks = list(db.scalars(select(Task).order_by(Task.id)))
    assert [t.payload["job_id"] for t in tasks] == [other.id, remote.id, visa.id]
    assert all(t.type == "prepare_application" and t.payload["then_fill"] and t.payload["automatic"] for t in tasks)
    assert db.query(Application).count() == 3  # visible in the tracker before preparation runs
    assert get_setting(db, "last_runs")["autofill"]["other"] == 1
    assert worker.queue_auto_applications(db, verified_since=since) == 1
    assert worker.queue_auto_applications(db, verified_since=since) == 0
    assert db.query(Application).count() == 4


def test_visa_and_remote_break_equal_fit_scores(db, job_factory):
    enable(db)
    since = utcnow() - timedelta(minutes=1)
    other = candidate(job_factory, "other-tie", fit_score=85)
    remote = candidate(job_factory, "remote-tie", remote_mode="remote", fit_score=85)
    visa = candidate(job_factory, "visa-tie", visa_status="confirmed", fit_score=85)
    db.commit()
    assert worker.queue_auto_applications(db, verified_since=since) == 3
    assert [t.payload["job_id"] for t in db.scalars(select(Task).order_by(Task.id))] == [visa.id, remote.id, other.id]


def test_disabled_and_priority_only_policy(db, job_factory):
    since = utcnow() - timedelta(minutes=1)
    candidate(job_factory, "visa", visa_status="confirmed")
    candidate(job_factory, "remote", remote_mode="remote")
    candidate(job_factory, "other")
    db.commit()
    assert worker.queue_auto_applications(db, verified_since=since) == 0
    enable(db, include_other_matches=False)
    assert worker.queue_auto_applications(db, verified_since=since) == 2


def test_existing_applications_are_never_reselected(db, job_factory):
    enable(db)
    for status in ("draft", "prepared", "awaiting_approval", "approved", "submitted", "submit_uncertain", "declined", "needs_manual"):
        job = candidate(job_factory, status, visa_status="confirmed")
        db.add(Application(job=job, status=status))
    db.commit()
    assert worker.queue_auto_applications(db, verified_since=utcnow() - timedelta(minutes=1)) == 0
    assert db.query(Task).count() == 0


@pytest.mark.parametrize("auto_submit", [False, True])
def test_full_discovery_chains_to_review_or_automatic_submission(db, job_factory, cv, monkeypatch, auto_submit):
    enable(db, auto_submit_enabled=auto_submit)
    job = candidate(job_factory, "cycle", visa_status="confirmed")
    db.commit()

    def discover(db, **kw):
        job.last_verified_at = utcnow()
        db.commit()
        return {"new_ids": [job.id], "companies": 1}

    calls = []
    def browser(db, app, mode, **kw):
        calls.append(mode)
        return {"ok": True, "outcome": "submitted" if mode == "submit" else "filled", "revision": app.revision, "content_hash": app.content_hash,
                "filled": [{"key": "name"}], "unmapped_required": [], "discovered": []}

    monkeypatch.setattr(worker, "run_discovery", discover)
    monkeypatch.setattr(workflow, "verify_job", lambda *a: True)
    monkeypatch.setattr(workflow.automation, "run_form", browser)
    enqueue(db, "discovery", {"trigger": "schedule"})
    db.commit()
    for expected in ("discovery", "prepare_application", "fill_form"):
        task = worker.run_one(db)
        assert task.type == expected and task.status == "done", task.error
    app = db.scalar(select(Application).where(Application.job_id == job.id))
    if auto_submit:
        assert app.status == "approved"
        task = worker.run_one(db)
        assert task.type == "submit_application" and task.status == "done" and task.result["ok"]
        assert app.status == "submitted" and app.job.stage == "submitted" and app.submitted_at
        assert calls == ["fill", "submit"] and app.automation_mode == "automatic"
        assert worker.run_one(db) is None
        return
    assert worker.run_one(db) is None
    assert app.status == "awaiting_approval" and app.job.stage == "awaiting_approval"
    assert app.approved_at is None and app.submitted_at is None and calls == ["fill"]
    assert db.query(Task).filter_by(type="submit_application").count() == 0


def test_three_hour_cadence_uses_search_start_and_does_not_overlap(db):
    now = utcnow()
    cfg = get_setting(db, "schedule")
    cfg.update(discovery_enabled=True, discovery_interval_hours=3, verify_enabled=False, email_sync_enabled=False)
    set_setting(db, "schedule", cfg)
    runs = {"discovery": {"started_at": (now - timedelta(hours=2, minutes=59)).isoformat() + "Z",
                          "at": (now - timedelta(hours=2, minutes=54)).isoformat() + "Z"}}
    set_setting(db, "last_runs", runs)
    db.commit()
    assert worker.scheduler_tick(db) == []
    runs["discovery"]["started_at"] = (now - timedelta(hours=3, seconds=1)).isoformat() + "Z"
    set_setting(db, "last_runs", runs)
    db.commit()
    assert worker.scheduler_tick(db) == ["discovery"]
    assert worker.scheduler_tick(db) == []


@pytest.mark.parametrize("step", ["prepare_application", "fill_form"])
def test_pausing_prevents_queued_automatic_work(db, job_factory, cv, step, monkeypatch):
    enable(db)
    job = candidate(job_factory, "pause")
    db.commit()
    worker.queue_auto_applications(db, verified_since=utcnow() - timedelta(minutes=1))
    if step == "fill_form":
        assert worker.run_one(db).type == "prepare_application"
    cfg = get_setting(db, "automation")
    cfg["auto_fill_enabled"] = False
    set_setting(db, "automation", cfg)
    db.commit()
    monkeypatch.setattr(workflow, "fill_application", lambda *a, **kw: pytest.fail("Paused work must not open a browser"))
    task = worker.run_one(db)
    assert task.type == step and task.result["skipped"]
    assert "paused" in db.scalar(select(Application)).last_error


@pytest.mark.parametrize("live,eligibility", [(None, "eligible"), (False, "eligible"), (True, "rejected")])
def test_automatic_fill_rechecks_live_eligibility(db, job_factory, cv, monkeypatch, live, eligibility):
    from app.preparation import prepare_application
    job = candidate(job_factory, "check")
    app = prepare_application(db, job, use_ai=False)
    db.commit()
    def verify(*args):
        job.eligibility = eligibility
        return live
    monkeypatch.setattr(workflow, "verify_job", verify)
    result = workflow.fill_application(db, app.id, automatic=True, runner=lambda *a, **kw: pytest.fail("Must not open a browser"))
    assert result["ok"] is False and app.last_error and app.submitted_at is None


def test_task_failure_is_visible_on_the_tracked_application(db, job_factory, monkeypatch):
    enable(db)
    candidate(job_factory, "failure")
    db.commit()
    worker.queue_auto_applications(db, verified_since=utcnow() - timedelta(minutes=1))
    def fail(*a, **kw):
        raise RuntimeError("Fixture preparation failed")
    monkeypatch.setattr(worker.preparation, "prepare_application", fail)
    assert worker.run_one(db).status == "failed"
    app = db.scalar(select(Application))
    assert app.status == "needs_manual" and "Fixture preparation failed" in app.last_error


def test_partial_board_refresh_does_not_start_a_full_application_cycle(db, monkeypatch):
    enable(db)
    monkeypatch.setattr(worker, "run_discovery", lambda *a, **kw: {"new_ids": []})
    monkeypatch.setattr(worker, "queue_auto_applications", lambda *a, **kw: pytest.fail("Partial search must not start a cycle"))
    worker.t_discovery(db, {"company_ids": [1]})


def filled_browser(db, app, mode, **kwargs):
    assert mode == 'fill'
    return {'ok': True, 'outcome': 'filled', 'revision': app.revision, 'content_hash': app.content_hash,
            'filled': [{'key': 'name'}], 'unmapped_required': [], 'discovered': []}


def ready_automatic(db, job_factory, monkeypatch):
    from app.preparation import prepare_application
    enable(db, auto_submit_enabled=True)
    app = prepare_application(db, candidate(job_factory, 'automatic'), use_ai=False)
    app.automation_mode = 'automatic'
    db.commit()
    monkeypatch.setattr(workflow, 'verify_job', lambda *a: True)
    assert workflow.fill_application(db, app.id, automatic=True, runner=filled_browser)['ok']
    assert app.status == 'approved'
    return app


@pytest.mark.parametrize('setting', ['auto_submit_enabled', 'auto_fill_enabled'])
def test_pausing_cancels_queued_automatic_submission(db, job_factory, cv, monkeypatch, setting):
    app = ready_automatic(db, job_factory, monkeypatch)
    enable(db, **{setting: False})
    monkeypatch.setattr(workflow.automation, 'run_form', lambda *a, **kw: pytest.fail('Paused submission opened a browser'))
    task = worker.run_one(db)
    assert task.type == 'submit_application' and not task.result['ok']
    assert app.status == 'awaiting_approval' and app.approved_at is None and app.submit_started_at is None
    assert worker.run_one(db) is None


@pytest.mark.parametrize('live,eligibility', [(None, 'eligible'), (False, 'eligible'), (True, 'rejected')])
def test_automatic_submission_rechecks_vacancy_and_never_retries(db, job_factory, cv, monkeypatch, live, eligibility):
    app = ready_automatic(db, job_factory, monkeypatch)
    def verify(db, job):
        job.eligibility = eligibility
        return live
    monkeypatch.setattr(workflow, 'verify_job', verify)
    monkeypatch.setattr(workflow.automation, 'run_form', lambda *a, **kw: pytest.fail('Unverified job submitted'))
    task = worker.run_one(db)
    assert not task.result['ok'] and app.status == 'failed' and app.submitted_at is None
    assert worker.run_one(db) is None


def test_manual_applications_still_wait_for_review_when_automatic_submission_enabled(db, job_factory, cv, monkeypatch):
    from app.preparation import prepare_application
    enable(db, auto_submit_enabled=True)
    app = prepare_application(db, candidate(job_factory, 'manual'), use_ai=False)
    db.commit()
    monkeypatch.setattr(workflow, 'verify_job', lambda *a: True)
    # Even a mistakenly automatic fill must not authorize a manual application.
    result = workflow.fill_application(db, app.id, runner=filled_browser)
    assert result['ok'] and app.status == 'awaiting_approval' and app.automation_mode == 'manual'
    assert db.query(Task).filter_by(type='submit_application').count() == 0


def test_unknown_required_question_stays_for_attention(db, job_factory, cv, monkeypatch):
    from app.preparation import prepare_application
    enable(db, auto_submit_enabled=True)
    app = prepare_application(db, candidate(job_factory, 'unknown'), use_ai=False)
    app.automation_mode = 'automatic'
    db.commit()
    monkeypatch.setattr(workflow, 'verify_job', lambda *a: True)
    def browser(db, app, mode, **kw):
        return {**filled_browser(db, app, mode), 'discovered': [
            {'key': 'custom', 'label': 'What is your favorite algorithm?', 'required': True, 'type': 'text'}]}
    result = workflow.fill_application(db, app.id, automatic=True, runner=browser)
    assert not result['ok'] and app.status == 'prepared' and app.issues
    assert db.query(Task).filter_by(type='submit_application').count() == 0


def test_manual_takeover_during_fill_prevents_automatic_submission(db, job_factory, cv, monkeypatch):
    from app.preparation import prepare_application
    from app.db import SessionLocal
    enable(db, auto_submit_enabled=True)
    app = prepare_application(db, candidate(job_factory, 'takeover'), use_ai=False)
    app.automation_mode = 'automatic'
    db.commit()
    monkeypatch.setattr(workflow, 'verify_job', lambda *a: True)
    def browser(db, app, mode, **kw):
        with SessionLocal() as other:
            other.get(Application, app.id).automation_mode = 'manual'
            other.commit()
        return filled_browser(db, app, mode)
    result = workflow.fill_application(db, app.id, automatic=True, runner=browser)
    assert not result['ok'] and app.automation_mode == 'manual'
    assert db.query(Task).filter_by(type='submit_application').count() == 0


def test_saved_consent_requires_exact_question_and_x_link_is_available(db, job_factory, profile):
    from app.preparation import resolve_answer, classify_field
    from app.schemas import StandardAnswer
    job = job_factory()
    profile.links.other = ['https://x.com/74H2v']
    assert resolve_answer({'label': 'X / Twitter URL', 'key': 'social'}, job, profile, '', None)['value'] == 'https://x.com/74H2v'
    question = 'I agree to the candidate privacy notice.'
    profile.standard_answers = [StandardAnswer(question=question, answer='Yes')]
    consent = {'label': question, 'key': 'consent', 'type': 'select', 'required': True, 'options': ['Yes', 'No']}
    assert resolve_answer(consent, job, profile, '', None)['value'] == 'Yes'
    consent['label'] = 'I agree to the candidate privacy notice and external sharing.'
    assert resolve_answer(consent, job, profile, '', None)['value'] is None
    assert classify_field('Please share my resume and contact information with external partners.') == 'consent'


def test_verified_profile_facts_do_not_fill_unknown_salary_dates_or_employment(db, job_factory, profile):
    from app.preparation import resolve_answer
    job = job_factory()
    profile.preferences.salary_min = 30000
    profile.preferences.salary_currency = 'MAD'
    profile.candidate_facts.age_18_or_older = True
    profile.candidate_facts.high_school_graduation_year = 2022
    profile.candidate_facts.latest_confirmed_employer = 'PHOVA Technology'
    profile.education[0].expected_graduation_year = 2027
    def answer(label, **kwargs):
        return resolve_answer({'key': label, 'label': label, **kwargs}, job, profile, '', None)['value']
    assert answer('Salary Expectations?') is None
    assert answer('Expected graduation year') == '2027'
    assert answer('Graduation Date', type='date') is None
    assert answer('Year of High School Graduation') == '2022'
    assert answer('Are you at least 18 years of age?', options=['Yes', 'No']) == 'Yes'
    assert answer('Current company') is None
    assert answer('Current/Last Company') == 'PHOVA Technology'
    assert answer('Notice Period (months)') is None
    assert answer('Have you previously been employed by Stripe?', options=['Yes', 'No']) is None
    assert answer('Are you a current government official?', options=['Yes', 'No']) is None


def test_latest_profile_policy_overrides_earlier_automatic_authorization(db, job_factory, cv, monkeypatch):
    from app.models import Profile
    from app.discovery import load_profile
    app = ready_automatic(db, job_factory, monkeypatch)
    profile = load_profile(db)
    profile.application_policy.require_final_approval = True
    db.get(Profile, 1).data = profile.model_dump()
    db.commit()
    monkeypatch.setattr(workflow.automation, 'run_form', lambda *a, **kw: pytest.fail('Latest approval requirement was ignored'))
    task = worker.run_one(db)
    assert not task.result['ok'] and app.approved_at is None and app.submitted_at is None


def test_full_refresh_resumes_ready_automatic_forms_by_fit_without_duplicates(db, job_factory, cv, monkeypatch):
    from app.preparation import prepare_application
    enable(db, auto_submit_enabled=True)
    since = utcnow() - timedelta(minutes=1)
    monkeypatch.setattr(workflow, 'verify_job', lambda *a: True)
    apps = {}
    for name, score, mode in [('lower', 65, 'automatic'), ('higher', 90, 'automatic'), ('manual', 99, 'manual'),
                              ('stale', 100, 'automatic'), ('blocked', 98, 'automatic')]:
        job = candidate(job_factory, name, fit_score=score)
        app = prepare_application(db, job, use_ai=False)
        app.automation_mode = mode
        db.commit()
        workflow.fill_application(db, app.id, runner=filled_browser)
        if name == 'stale':
            job.last_verified_at = since - timedelta(seconds=1)
        if name == 'blocked':
            app.issues = [{'code': 'missing_answer', 'blocking': True}]
        apps[name] = app
    db.commit()
    assert worker.queue_ready_submissions(db, verified_since=since) == 2
    tasks = list(db.scalars(select(Task).where(Task.type == 'submit_application').order_by(Task.id)))
    assert [t.payload['application_id'] for t in tasks] == [apps['higher'].id, apps['lower'].id]
    assert all(t.payload['automatic'] for t in tasks)
    assert worker.queue_ready_submissions(db, verified_since=since) == 0
    assert apps['manual'].status == apps['stale'].status == apps['blocked'].status == 'awaiting_approval'
