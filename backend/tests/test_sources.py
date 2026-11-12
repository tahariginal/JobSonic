import json

import httpx
from sqlalchemy import select

from app.discovery import run_discovery, verify_job
from app.models import Company, Event, Job, Notification
from app.sources import ADAPTERS, PoliteClient

GH = {"jobs": [
    {"id": 101, "title": "Junior Backend Engineer", "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/101",
     "location": {"name": "Berlin, Germany"}, "departments": [{"name": "Engineering"}], "first_published": "2026-10-01T10:00:00-04:00",
     "content": "&lt;h3&gt;What you&#39;ll do&lt;/h3&gt;&lt;ul&gt;&lt;li&gt;Build APIs in C++&lt;/li&gt;&lt;/ul&gt;&lt;p&gt;0-2 years of experience. We offer visa sponsorship and relocation support.&lt;/p&gt;"},
    {"id": 102, "title": "Senior Software Engineer", "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/102",
     "location": {"name": "London"}, "content": "&lt;p&gt;8+ years of experience.&lt;/p&gt;"},
    {"id": 103, "title": "Account Executive", "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/103",
     "location": {"name": "Paris"}, "content": "&lt;p&gt;Sell.&lt;/p&gt;"},
]}
LEVER = [{"id": "abc-1", "text": "Graduate Software Engineer", "hostedUrl": "https://jobs.lever.co/beta/abc-1",
          "applyUrl": "https://jobs.lever.co/beta/abc-1/apply", "categories": {"location": "Amsterdam", "commitment": "Full-time", "team": "Platform"},
          "country": "NL", "workplaceType": "hybrid", "createdAt": 1760000000000,
          "description": "<p>Join us.</p>", "lists": [{"text": "What you'll do", "content": "<li>Ship features</li>"}],
          "additional": "<p>Sponsorship may be available for exceptional candidates.</p>",
          "salaryRange": {"min": 50000, "max": 60000, "currency": "EUR", "interval": "per-year-salary"}}]
ASHBY = {"jobs": [
    {"id": "u-1", "title": "AI Agent Engineer", "location": "Remote (Worldwide)", "isRemote": True, "isListed": True,
     "jobUrl": "https://jobs.ashbyhq.com/gamma/u-1", "applyUrl": "https://jobs.ashbyhq.com/gamma/u-1/application",
     "descriptionHtml": "<p>Work from anywhere in the world on RAG and MCP agents.</p>", "descriptionPlain": "Work from anywhere in the world on RAG and MCP agents.",
     "publishedAt": "2026-10-05T00:00:00.000+00:00", "employmentType": "FullTime",
     "compensation": {"compensationTierSummary": "$90K – $110K", "summaryComponents": [{"compensationType": "Salary", "minValue": 90000, "maxValue": 110000, "currencyCode": "USD"}]}},
    {"id": "u-2", "title": "Hidden Engineer", "isListed": False, "jobUrl": "https://jobs.ashbyhq.com/gamma/u-2", "descriptionPlain": "x"},
]}


class FakeBoards:
    def __init__(self):
        self.gh = json.loads(json.dumps(GH))
        self.lever = json.loads(json.dumps(LEVER))
        self.ashby = json.loads(json.dumps(ASHBY))
        self.calls = []
        self.fail = set()

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.calls.append(url)
        if any(f in url for f in self.fail):
            return httpx.Response(404)
        if "boards-api.greenhouse.io/v1/boards/acme/jobs/" in url:
            jid = int(url.rstrip("/").split("/")[-1].split("?")[0])
            return httpx.Response(200 if any(j["id"] == jid for j in self.gh["jobs"]) else 404, json={})
        if "boards-api.greenhouse.io/v1/boards/acme/jobs" in url:
            return httpx.Response(200, json=self.gh)
        if "api.lever.co/v0/postings/beta" in url:
            return httpx.Response(200, json=self.lever)
        if "api.ashbyhq.com/posting-api/job-board/gamma" in url:
            return httpx.Response(200, json=self.ashby)
        return httpx.Response(404)

    def client(self):
        return PoliteClient(min_interval=0, transport=httpx.MockTransport(self.handler))


def setup(db):
    for n, p, t in (("Acme", "greenhouse", "acme"), ("Beta", "lever", "beta"), ("Gamma", "ashby", "gamma")):
        db.add(Company(name=n, provider=p, board_token=t))
    db.commit()


def test_adapters_parse_official_payloads():
    fb = FakeBoards()
    c = fb.client()
    gh = ADAPTERS["greenhouse"].fetch(c, "acme")
    assert gh[0].external_id == "101" and "Build APIs in C++" in gh[0].description_text and gh[0].posted_at.year == 2026
    lv = ADAPTERS["lever"].fetch(c, "beta")[0]
    assert lv.apply_url.endswith("/apply") and lv.salary["min"] == 50000 and "Ship features" in lv.description_text
    ab = ADAPTERS["ashby"].fetch(c, "gamma")
    assert len(ab) == 1 and ab[0].remote_hint is True and ab[0].salary["currency"] == "USD"


def test_discovery_filters_classifies_and_stores_provenance(db, profile):
    setup(db)
    fb = FakeBoards()
    out = run_discovery(db, client=fb.client(), trigger="test")
    assert out["new"] == 4 and out["fetched"] == 5 and out["errors"] == 0
    jobs = {j.title: j for j in db.scalars(select(Job))}
    assert "Account Executive" not in jobs and "Hidden Engineer" not in jobs
    j = jobs["Junior Backend Engineer"]
    assert j.eligibility == "eligible" and j.visa_status == "confirmed" and j.country == "Germany"
    assert j.canonical_url == "https://job-boards.greenhouse.io/acme/jobs/101" and j.apply_url.startswith("https://job-boards.greenhouse.io/")
    assert j.discovered_at and j.last_verified_at and j.fingerprint and j.external_id == "101"
    assert j.summary == "Build APIs in C++" and j.fit_stars >= 4
    assert jobs["Senior Software Engineer"].eligibility == "rejected"
    lv = jobs["Graduate Software Engineer"]
    assert lv.visa_status == "conditional" and lv.remote_mode == "hybrid" and lv.country == "Netherlands" and lv.salary_min == 50000
    ab = jobs["AI Agent Engineer"]
    assert ab.remote_mode == "remote" and ab.remote_from_morocco == "likely" and ab.role_family == "applied_ai"
    types = [e.type for e in db.scalars(select(Event))]
    assert "discovery.started" in types and "discovery.completed" in types


def test_rerun_is_deduplicated_and_quiet(db, profile):
    setup(db)
    fb = FakeBoards()
    run_discovery(db, client=fb.client())
    n_notes = db.query(Notification).count()
    assert n_notes >= 1
    out = run_discovery(db, client=fb.client())
    assert out["new"] == 0 and out["updated"] == 0
    assert db.query(Job).count() == 4
    assert db.query(Notification).count() == n_notes  # no repeated alerts for unchanged vacancies


def test_changed_and_closed_vacancies(db, profile):
    setup(db)
    fb = FakeBoards()
    run_discovery(db, client=fb.client())
    j = db.scalar(select(Job).where(Job.external_id == "101"))
    j.seen = True
    db.commit()
    fb.gh["jobs"][0]["content"] = "&lt;p&gt;5+ years of experience required.&lt;/p&gt;"
    fb.lever.clear()
    out = run_discovery(db, client=fb.client())
    assert out["updated"] == 1 and out["closed"] == 1
    db.expire_all()
    j = db.scalar(select(Job).where(Job.external_id == "101"))
    assert j.eligibility == "rejected" and j.updated_content_at is not None and j.seen is False
    closed = db.scalar(select(Job).where(Job.external_id == "abc-1"))
    assert closed.is_active is False and closed.closed_at is not None and closed.eligibility == "rejected"
    # it comes back -> reopened, not duplicated
    fb.lever.extend(LEVER)
    out = run_discovery(db, client=fb.client())
    db.expire_all()
    assert db.scalar(select(Job).where(Job.external_id == "abc-1")).is_active is True and db.query(Job).count() == 4


def test_one_failing_source_does_not_stop_the_run(db, profile):
    setup(db)
    fb = FakeBoards()
    fb.fail.add("api.lever.co")
    out = run_discovery(db, client=fb.client())
    assert out["errors"] == 1 and out["new"] == 3
    assert db.scalar(select(Company).where(Company.provider == "lever")).last_status.startswith("error")


def test_verify_single_job(db, profile):
    setup(db)
    fb = FakeBoards()
    run_discovery(db, client=fb.client())
    j = db.scalar(select(Job).where(Job.external_id == "101"))
    assert verify_job(db, j, client=fb.client()) is True
    fb.gh["jobs"] = fb.gh["jobs"][1:]
    assert verify_job(db, j, client=fb.client()) is False
    assert j.is_active is False and j.eligibility == "rejected"
