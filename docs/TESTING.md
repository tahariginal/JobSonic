# Testing

## Run

```bash
cd backend  && .venv/bin/python -m pytest -q            # 181 tests, ~2 min (11 launch a real browser)
cd frontend && npx playwright test                      # 15 end-to-end tests, ~1 min
cd frontend && npx next build                           # type-check + production build
```

Tests use a temporary database and never touch `data/`. **No test contacts an employer site or
submits a real application**: source adapters are tested with recorded-shape payloads through a
mock transport, Gmail with a mocked Google, and the form agent against local fixture pages on
`127.0.0.1` that record what would have been sent.

## Coverage map

| Requirement | Where |
|---|---|
| Job discovery, ATS parsing | `test_sources.py` (Greenhouse, Lever, Ashby payloads; provenance fields) |
| Deduplication, change/close/reopen detection, quiet re-runs | `test_sources.py` |
| Eligibility filtering, Needs Review | `test_analysis.py` |
| Visa classifications and evidence | `test_analysis.py` (incl. 12 sentences from real postings) |
| Matching / fit score | `test_analysis.py` |
| AI gating, budgets, cache, no invented evidence | `test_ai_worker.py` |
| Application state transitions | `test_pipeline.py` |
| Approval authorization (exact version) | `test_pipeline.py`, `test_api.py` |
| Duplicate submission prevention | `test_pipeline.py`, `test_automation.py` |
| Form filling (Lever-, Greenhouse-, Ashby-style) | `test_automation.py` (real Chromium) |
| Browser failure recovery, restart mid-submit, unknown outcome | `test_pipeline.py`, `test_automation.py` |
| CAPTCHA and closed-posting detection | `test_automation.py` |
| Email classification and matching, OAuth flow | `test_email.py` |
| API endpoints, auth, CSRF, rate limit, uploads, headers | `test_api.py` |
| Worker queue, bounded retries, scheduler | `test_ai_worker.py` |
| Dashboard interactions | `frontend/e2e/dashboard.spec.ts` |
| Responsive behaviour (phone, tablet) | `frontend/e2e/responsive.spec.ts` |

## Results on this deployment (2026-11-12)

- Backend: **181 passed**.
- Dashboard end-to-end: **15 passed** (desktop 1440px, Pixel 7, tablet 820px).
- Production build and type-check: passed.

## Checks against the real world (manual, recorded here)

| Check | Result |
|---|---|
| Full search across 165 employer boards | 18,762 postings read, 4,516 relevant stored, 0 source errors, about 5 minutes |
| Audit of every visa classification pattern on that data | Found and fixed 5 false-positive patterns; sentences added as regression tests |
| Field detection on 9 live forms (3 per ATS), read-only: nothing typed, uploaded or sent | All loaded; every prepared answer mapped to a field; extra required questions correctly listed for review |
| One minimal call through the Claude CLI integration | Worked (tools disabled, ~3 s). AI left off. |
| Service restart | Data intact, worker recovered, services enabled at boot |
| Backup and restore of the archive | Restored copy passes SQLite integrity check |

## Not tested

- A real submission to a live employer form (needs your profile, CV and approval).
- Gmail against real Google (needs your OAuth client).
- Telegram delivery (needs your bot).
- A full server reboot (services are enabled at boot and survive `systemctl restart`; a reboot would
  also restart your other services, so it was left to you).
