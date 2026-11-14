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
    db.commit()


def candidate(job_factory, external_id, **changes):
    job = job_factory(external_id=external_id)
    job.eligibility, job.visa_status, job.remote_mode = "eligible", "unverified", "onsite"
    job.last_verified_at = utcnow()
    for key, value in changes.items():
        setattr(job, key, value)
    return job


def test_priority_limit_freshness_and_duplicate_protection(db, job_factory):
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
    assert [t.payload["job_id"] for t in tasks] == [visa.id, remote.id, other.id]
    assert all(t.type == "prepare_application" and t.payload["then_fill"] and t.payload["automatic"] for t in tasks)
    assert db.query(Application).count() == 3  # visible in the tracker before preparation runs
    assert get_setting(db, "last_runs")["autofill"]["other"] == 1
    assert worker.queue_auto_applications(db, verified_since=since) == 1
    assert worker.queue_auto_applications(db, verified_since=since) == 0
    assert db.query(Application).count() == 4


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


def test_full_discovery_chains_prepare_fill_and_stops_at_approval(db, job_factory, cv, monkeypatch):
    enable(db)
    job = candidate(job_factory, "cycle", visa_status="confirmed")
    db.commit()

    def discover(db, **kw):
        job.last_verified_at = utcnow()
        db.commit()
        return {"new_ids": [job.id], "companies": 1}

    calls = []
    def browser(db, app, mode, **kw):
        calls.append(mode)
        return {"ok": True, "outcome": "filled", "revision": app.revision, "content_hash": app.content_hash,
                "filled": [{"key": "name"}], "unmapped_required": [], "discovered": []}

    monkeypatch.setattr(worker, "run_discovery", discover)
    monkeypatch.setattr(workflow, "verify_job", lambda *a: True)
    monkeypatch.setattr(workflow.automation, "run_form", browser)
    enqueue(db, "discovery", {"trigger": "schedule"})
    db.commit()
    for expected in ("discovery", "prepare_application", "fill_form"):
        task = worker.run_one(db)
        assert task.type == expected and task.status == "done", task.error
    assert worker.run_one(db) is None
    app = db.scalar(select(Application).where(Application.job_id == job.id))
    assert app.status == "awaiting_approval" and app.job.stage == "awaiting_approval"
    assert app.approved_at is None and app.submitted_at is None and calls == ["fill"]
    assert db.query(Task).filter_by(type="submit_application").count() == 0


def test_four_hour_cadence_uses_search_start_and_does_not_overlap(db):
    now = utcnow()
    cfg = get_setting(db, "schedule")
    cfg.update(discovery_enabled=True, discovery_interval_hours=4, verify_enabled=False, email_sync_enabled=False)
    set_setting(db, "schedule", cfg)
    runs = {"discovery": {"started_at": (now - timedelta(hours=3, minutes=59)).isoformat() + "Z",
                          "at": (now - timedelta(hours=3, minutes=54)).isoformat() + "Z"}}
    set_setting(db, "last_runs", runs)
    db.commit()
    assert worker.scheduler_tick(db) == []
    runs["discovery"]["started_at"] = (now - timedelta(hours=4, seconds=1)).isoformat() + "Z"
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
