# Job sources

## What is queried

Only employers' **own job boards**, through the public, documented job-board APIs of their
applicant tracking system. Every stored URL is the employer's official posting.

| Provider | Endpoint used | Verification of one job |
|---|---|---|
| Greenhouse | `boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true` | `.../jobs/{id}` (200 / 404) |
| Lever | `api.lever.co/v0/postings/{board}?mode=json` | `.../{id}` |
| Ashby | `api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true` | board re-read |

These endpoints exist so that job listings can be displayed elsewhere; they need no login.
The client identifies itself (`SonicJobs/1.0`), waits at least 0.6 s between requests to the same
host, honours `Retry-After`, retries at most twice, and uses no anti-bot techniques.

## The seed list

`backend/app/data/companies_seed.json`: 165 boards. Each one was checked on 2026-11-11: the board
answered with open jobs **and** its official name was read back. Eight guessed IDs that resolved
to a different company were dropped. Regions covered include Europe, Asia, the Middle East,
North America and remote-first employers.

It is a starting set, not a complete market view. Add employers you care about.

## Adding a source

Dashboard → Settings → Job sources → pick the provider and enter the board ID (the last part of the
careers URL: `job-boards.greenhouse.io/<id>`, `jobs.lever.co/<id>`, `jobs.ashbyhq.com/<id>`).
The board is fetched from the official API first; unknown IDs are refused. It is searched immediately.

Disable a source with its toggle. Jobs already found stay in the database.

## Adding a new provider (code)

1. In `backend/app/sources.py` create a subclass of `Adapter` with `provider`, `fetch()` returning
   `RawJob` items, `is_live()` and `form_url()`.
2. Register it in `ADAPTERS`.
3. Allow the provider name in `CompanyIn` (`main.py`) and add it to the provider select in
   `frontend/src/app/(app)/settings/page.tsx`.
4. Add a payload test in `tests/test_sources.py`; add `BASE_FIELDS` in `preparation.py` if its
   application form has standard fields.

## What is filtered at ingestion

Only engineering titles are stored (`normalize.is_relevant_title`): the title must contain
engineer / developer / programmer and must not be sales, support, hardware, management, data
science, security, SRE and similar. Adjust with include / exclude keywords in Settings.

## Not supported, and why

| Source | Reason |
|---|---|
| Workday | No public job API; each tenant is a separate site with session-bound requests. Technically possible per company, but fragile. Not built. |
| LinkedIn, Indeed, Glassdoor | Terms forbid automated collection, and they block server traffic. Deliberately not used. |
| Public job boards (Remotive, Arbeitnow, …) | Not integrated yet. They would be discovery-only: a board listing would still need verifying against the employer's own posting before it counts. |
| SmartRecruiters, Workable, Recruitee, Personio | Have public posting APIs; good candidates for the next adapters (see ROADMAP). |
