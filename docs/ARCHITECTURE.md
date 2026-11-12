# Architecture

One Python service and one worker process, one SQLite file, static frontend. No microservices.

```
 browser ──HTTPS──▶ (Tailscale Serve or nginx) ──▶ uvicorn 127.0.0.1:8790
                                                   ├─ /api/*        FastAPI (app/main.py)
                                                   └─ /*            static dashboard (frontend/out)
                                                         │
                                              SQLite (WAL)  data/sonic.db
                                                         │
 sonic-jobs-worker (app/worker.py) ── task queue + scheduler, one task at a time
        ├─ discovery ─▶ Greenhouse / Lever / Ashby public job-board APIs
        ├─ prepare / fill / submit ─▶ headless Chromium (Playwright), one browser at a time
        ├─ email sync ─▶ Gmail API (read-only)            [needs OAuth client]
        └─ ai evaluate / write ─▶ local `claude -p`       [off by default]
```

## Modules (`backend/app`)

| Module | Responsibility |
|---|---|
| `config.py` | Settings from `.env` (`SONIC_*`). Secrets never live in code. |
| `models.py`, `db.py`, `migrations/` | SQLAlchemy models, SQLite in WAL mode, Alembic migrations. |
| `schemas.py` | Candidate profile schema and the seed built only from stated facts. |
| `sources.py` | **job_sources**: one adapter per ATS (`fetch`, `is_live`, `form_url`). Polite HTTP client. |
| `normalize.py` | **job_normalization**: text, role family, seniority, years, location, salary, summary, fingerprint. |
| `discovery.py` | **job_verification** + pipeline: fetch → dedupe/upsert → analyse → notify. |
| `analysis.py` | **visa_intelligence**, eligibility rules and **matching** (fit score). Pure functions. |
| `ai.py` | Optional AI layer: switches, budgets, cache, usage log. |
| `preparation.py` | **application_preparation**: CV choice, form schema, answers, cover letter, AI review. |
| `automation.py` | **browser_automation**: field detection, filling, screenshots, guarded submit. |
| `pipeline.py` | **approval_workflow**: stage machine, content hash, approval, single-use submit gate. |
| `workflow.py` | Glue for the two browser workflows (fill for review, approved submit). |
| `emailing.py` | **email_integration** (Gmail OAuth, classification, matching) and Telegram. |
| `core.py` | Settings store, activity events, **notifications**, **audit_logging**, task queue. |
| `worker.py` | Queue runner, scheduler, crash recovery, housekeeping. |
| `main.py` | HTTP API, auth, security headers, **analytics** endpoints, static hosting. |
| `backup.py`, `cli.py` | Backups and admin commands. |

## Data model (main tables)

`companies` (sources) → `jobs` (posting, analysis, stage) → `applications` (answers, revision,
content hash, approval, submission) → `material_versions`, `approval_events`, `screenshots`.
Also `events` (activity feed), `notifications`, `tasks` (queue), `ai_usage`, `ai_cache`,
`email_accounts`, `email_messages`, `audit_log`, `profile`, `documents`, `users`, `auth_sessions`, `settings`.

Every job stores: official URL, source URL, external job ID, discovery time, last verification
time and a content fingerprint. Uniqueness: `(provider, company, external_id)` plus canonical URL.

## Key design decisions

- **Rules before AI.** Title relevance, seniority, years, degree, language, visa wording, scoring are
  regular code with tests. A full search of ~19,000 postings uses zero model calls.
- **Evidence, not claims.** Each visa or eligibility finding stores the quoted sentence, the source
  URL, the check time and a kind: `verified` (quote from the posting), `unverified` (nothing found),
  `ai` (model interpretation). An AI visa claim is only accepted if its quote is found verbatim in
  the posting.
- **Approval is bound to content.** `content_hash` covers job, URL, CV file hash, cover letter and
  every answer. Approval stores `(revision, hash)`. Any edit bumps the revision and voids approval.
- **Submit gate.** `pipeline.begin_submit` checks status, key, revision, stored hash and a freshly
  recomputed hash, then flips to `submitting` in the same transaction. A second attempt, a retry or a
  restarted task cannot pass. A crash mid-submit becomes `submit_uncertain` and is never retried.
- **Static frontend.** Next.js is exported to plain files; no Node process runs in production.
- **SQLite first.** Models use portable SQLAlchemy types; moving to PostgreSQL means changing
  `SONIC_DATABASE_URL` and running the migrations (the JSON columns and date functions used in
  `main.py` analytics would need a small review).

## Pipeline stages

`discovered → verified → shortlisted → preparing → awaiting_approval → submitted → interview → offer / rejected` (+ hidden `archived`).

Manual moves are limited to what makes sense (`pipeline.MANUAL_TRANSITIONS`). A job reaches
*Awaiting approval* only when its form was filled, and *Submitted* only through approval or the
explicit "Mark as submitted manually" action.

## Charts

Chart colours were checked with a colour-vision validator on the dark surface: one hue
(`#c98500`) for magnitude; visa states use five separated hues and always carry a text label.
Every chart has a table view.
