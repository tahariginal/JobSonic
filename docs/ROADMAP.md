# Status and roadmap

## Implemented and verified

- Discovery from 165 verified Greenhouse / Lever / Ashby employer boards; manual and scheduled runs.
- Provenance, dedupe, change detection, closed-vacancy detection, single-job re-verification.
- Rule-based eligibility with a Needs Review queue and manual override.
- Visa / relocation / remote evidence with quotes, source URL and check date.
- Explainable 1–5★ fit rating.
- Candidate profile editor, CV upload and selection.
- Application preparation, version history, issues list.
- Form agent: field detection, filling, uploads, screenshots, CAPTCHA / closed detection.
- Approval bound to an exact version; single-use submit; crash-safe recovery.
- Dashboard: overview, jobs table, pipeline board, approval inbox, application detail, activity,
  analytics, profile, settings; responsive; keyboard accessible.
- Auth, CSRF, rate limiting, encrypted secrets, audit log, daily backups, health endpoint.
- systemd deployment that starts on boot.

## Partially implemented

| Item | What works | What is missing |
|---|---|---|
| Live form submission | Full flow proven on fixture forms; field detection verified on 9 live forms | No real application has been submitted yet. Expect some sites to challenge headless submissions (reCAPTCHA is present on most); those hand over to you. |
| Custom dropdowns on live forms | Native selects, radios, checkboxes, text, file | Searchable dropdowns (e.g. Greenhouse School / Degree / Location) are best-effort; unmatched ones are raised as "needs your input" or manual |
| "What you'll do" summary | Bullets under a responsibilities heading | Falls back to the opening sentences when a posting has no such section |
| CV tailoring | Chooses the best CV by role tag | Does not rewrite the CV file itself |
| Remote-from-Morocco | Detects "worldwide" and country-restricted remote | Cannot confirm Morocco specifically unless the posting says so |
| Salary | Structured pay ranges and explicit ranges in text | Many postings state none |

## Needs external credentials or a decision from you

| Item | What you need to provide |
|---|---|
| Phone / HTTPS access | Enable Tailscale Serve (one click) **or** approve public exposure via nginx |
| Your profile | Name, email, phone, languages, start date, at least one CV |
| Gmail tracking | A Google Cloud OAuth client (ID + secret) and `SONIC_PUBLIC_BASE_URL` |
| Telegram alerts | Bot token and chat ID |
| AI | Your go-ahead to run the Claude CLI unattended on your subscription (`AI_COSTS.md`) |

## Always needs your approval

Every submission; ticking consent boxes; anything the profile cannot answer; continuing past a
CAPTCHA or login; public exposure; enabling AI; any email reply (the system cannot send email).

## Not supported

- Workday and other session-based career sites.
- LinkedIn / Indeed / Glassdoor collection or "Easy Apply".
- Bypassing CAPTCHA, MFA or bot protection.
- Sending or replying to email.
- Metered Anthropic API billing.
- Multiple users.

## Recommended next steps

1. Fill in the profile and upload a CV; submit one real application end to end and review the result.
2. Enable Tailscale HTTPS so approvals work from the phone.
3. Add your skills (languages, frameworks) to the profile: the fit score depends on them.
4. Add employers you specifically want (Settings → Job sources).
5. More adapters: SmartRecruiters, Workable, Recruitee, Personio; a discovery-only public-board
   adapter with verification against the employer posting.
6. Second sign-in factor (TOTP) before any public exposure.
7. Off-server backup copy.
8. Remote assisted browser (view and click in the agent's browser from the dashboard) for forms
   that need a human check.
9. Follow-up reminders (no reply after N days) and interview notes.
10. Optional metered-API AI mode with explicit budget, if you ever prefer it over the subscription.
