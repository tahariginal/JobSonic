# SONIC JOBS

Personal job discovery and application control center. It runs on one small server, finds junior
engineering jobs on employers' official job boards, checks eligibility and visa evidence with
deterministic rules, prepares applications, fills the real application form in a headless browser,
and **stops for your approval before anything is sent**.

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
| Discovery from Greenhouse, Lever, Ashby (165 verified employer boards) | Working, runs every 12 h |
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
3. **Jobs**: review matches. Open a job to see the quoted evidence for visa and eligibility.
4. **Shortlist → Prepare application**. Answer anything marked "Needs your input".
5. **Fill form for review**: the agent fills the employer's form and takes a screenshot.
6. **Approvals**: check exactly what will be sent, then approve, request changes or reject.
7. Track results in **Pipeline**, **Activity** and **Analytics**.

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
