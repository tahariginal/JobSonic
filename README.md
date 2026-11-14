# SONIC JOBS

Personal job discovery and application control center. It runs on one small server, finds junior
engineering jobs on employers' official job boards, checks eligibility and visa evidence with
deterministic rules, prepares applications, fills the real application form in a headless browser,
and supports both **automatic submission using saved answers** and **manual review before sending**.
Automatic submission is enabled explicitly in Settings and can be paused at any time.

Principle: scripts do the repetitive work. AI is optional, off by default, and only used when
reasoning is needed.

## What is here

| Path | What |
|---|---|
| `backend/app` | FastAPI API, worker, discovery, analysis, form agent (Python 3.12) |
| `backend/tests` | 181 automated tests, including real-browser form tests against local fixture forms |
| `frontend` | Next.js + TypeScript + Tailwind dashboard, exported as static files and served by the API |
| `frontend/e2e` | 15 Playwright end-to-end tests of the dashboard (desktop, tablet, phone) |
| `deploy` | systemd units, install script, access helpers |
| `docs` | Architecture, deployment, security, testing, sources, AI costs, workflow, roadmap |
| `data/` | SQLite database, uploaded CVs, form screenshots, backups (not in git, owner-only) |

## Status at a glance

| Area | State |
|---|---|
| Discovery from Greenhouse, Lever, Ashby (165 verified employer boards) | Working, configurable search interval |
| Dedupe, change detection, closed-vacancy detection | Working |
| Eligibility filter, Needs Review queue, visa evidence with quotes | Working (rules, no AI) |
| Fit rating 1–5 with explanation | Working (rules); AI refinement optional |
| Dashboard: overview, jobs, pipeline, approvals, application, activity, analytics, profile, settings | Working |
| Application preparation (CV choice, answers from profile, template cover letter) | Working |
| Browser form filling with screenshots, pause for approval | Working on fixture forms; field detection verified read-only on 9 live forms |
| Approved submission (exactly once, never retried when uncertain) | Working on fixture forms; **not yet exercised on a live employer form** |
| Gmail tracking (read-only OAuth) | Built and tested with mocked Google; **needs your Google OAuth client** |
| Telegram alerts | Built; **needs your bot token** |
| AI (cover letters, free-text answers, deeper job review) | Built and smoke-tested; **off until you switch it on** |
| HTTPS access from your phone | **Needs one decision from you** (see docs/DEPLOYMENT.md) |

Details and limits for each item: `docs/ROADMAP.md`.

## Daily use

1. Open the dashboard and sign in (`docs/DEPLOYMENT.md` → Access).
2. **Profile**: fill in name, email, phone, languages, start date, and upload a CV. Forms are only
   ever filled with what you enter here.
   Under **Standard answers**, edit the reusable “Why this company?” answer used for motivation
   questions, including when AI is off. Start-date questions use your saved earliest start date.
   Saving your profile also resolves answerable gaps in pending applications; manual answers and
   approved or submitted applications are preserved.
3. **Jobs**: review matches. Open a job to see the quoted evidence for visa and eligibility.
4. **Shortlist → Prepare application**. Answer anything marked "Needs your input".
5. **Fill form for review**: the agent fills the employer's form and takes a screenshot.
6. **Approvals**: check exactly what will be sent, then approve, request changes or reject.
7. Open **Application tracker** in the sidebar to see every company and role with an application,
   form progress, approval/submission status, and dates. Search by company or role, filter by status,
   and open the saved application to review its answers, screenshots, and history. **Pipeline**,
   **Activity** and **Analytics** provide the wider view.

For a recurring search-to-fill cycle, use **Settings → Search & schedule**: enable automatic job
search, choose the interval (default **3 hours**), and enable **Automatically fill applications**.
Enable **Automatically submit applications** to authorize completed scheduled applications to be
sent using your saved answers and CV, without individual approval.
Each full search queues up to the configured number of new eligible applications (default 20),
starting with the highest fit scores. Confirmed visa sponsorship and remote roles break ties;
other eligible matches are included when enabled.
Only jobs freshly verified on enabled official boards are selected. Existing applications and
archived jobs are skipped; unresolved questions and failed attempts remain in the tracker for review.
Forms are re-verified before filling and submission. Missing answers, human checks and uncertain
outcomes stay in the tracker while other applications continue; facts and consents are never guessed.
Saving missing profile answers resumes eligible automatic forms when all required answers are available.
The worker runs this cycle even when the dashboard is closed. Pause automatic filling or submission
in Settings to stop pending automatic sends. Applications you prepare from Jobs use manual review;
each application also has an **Application mode** control for switching between automatic and manual.
The tracker refreshes automatically and records confirmed submissions, dates, screenshots and errors.
Each full search also picks up completed automatic applications waiting under an earlier review-only
setting, rechecks their eligibility and saved authorization, and queues them by fit score. Manual
applications and unknown submission outcomes are excluded from this recovery.

The persistent profile also records confirmed education years, adult eligibility, current versus
previous employment, consent preferences and unresolved facts. An unconfirmed salary period is
never treated as a yearly amount, used as a salary floor, or submitted as a numerical expectation.
Your profile's final-approval requirement takes precedence over automatic submission; saving that
requirement turns automatic submission off. Consent choices require an answer to the exact question.

After updating an existing installation, run `backend/.venv/bin/alembic -c backend/alembic.ini upgrade head`
from the project root (or `.venv/bin/alembic upgrade head` from `backend/`) before restarting the services.

## Service control

```bash
sudo systemctl status  sonic-jobs-api sonic-jobs-worker
sudo systemctl restart sonic-jobs-api sonic-jobs-worker
sudo systemctl stop    sonic-jobs-api sonic-jobs-worker     # stop everything
journalctl -u sonic-jobs-worker -f                          # live worker log
curl -s http://127.0.0.1:8790/api/health                    # health check
```

Admin commands (run from `backend/`):

```bash
.venv/bin/python -m app.cli create-user admin          # set a new password (prompts)
.venv/bin/python -m app.cli discover                   # run one search in the foreground
.venv/bin/python -m app.backup                         # back up now
```
