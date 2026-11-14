# Security

The system stores your CV, contact details, application history and (optionally) a Gmail token.

## Controls in place

| Area | Control |
|---|---|
| Network exposure | API binds to `127.0.0.1:8790` only. Verified unreachable on the public and Tailscale IPs. No debugging ports. API docs endpoints disabled. |
| Authentication | Single account. Password hashed with Argon2id. Unknown users are verified against a dummy hash. |
| Sessions | Random 320-bit token, stored hashed (SHA-256). Cookie is HttpOnly, SameSite=Lax, Secure. 14-day expiry. Sign-out deletes the session. |
| CSRF | Every state-changing request needs the per-session `X-CSRF-Token` header. |
| Rate limiting | Sign-in: 6 attempts / 5 minutes per address. API: 600 requests / minute per session. |
| Input validation | Pydantic models on every endpoint; settings accept only known keys, typed and bounded; source IDs restricted to `[A-Za-z0-9._-]`. |
| File uploads | PDF/DOCX/TXT only, 5 MB limit, content must match the extension, stored under random names (mode 600), served only to the signed-in user as downloads. |
| Secrets | `.env` (mode 600), never in git (`.gitignore`). Gmail refresh token, Google client secret and Telegram bot token are encrypted with Fernet and never returned by the API. |
| OAuth | Gmail scope is `gmail.readonly` only. Single-use `state`, and the callback also requires a signed-in session. |
| Headers | CSP (`default-src 'self'`, no framing), `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy: no-referrer`, HSTS, `Cache-Control: no-store` on the API. |
| Filesystem | `data/` is mode 700; services run as an unprivileged user with `NoNewPrivileges`, `PrivateTmp`, `ProtectSystem=full`, memory and CPU caps. |
| Browser isolation | A fresh browser context per form (no cookies kept), downloads disabled, one browser at a time, always closed, time-limited. |
| AI isolation | The model runs with all tools disabled, in an empty temp directory, with no API key in its environment. Job text is treated as untrusted; output must parse as JSON and is validated. |
| Audit | Sign-ins (and failures), approvals, edits, settings and source changes are written to `audit_log` (Settings → System). |
| Backups | Daily, owner-only files, 14 kept. |

## Application safety rules (enforced in code and tests)

- Submission requires authorization of the exact version (job + CV + every answer), either your
  individual approval or your explicitly enabled automatic-submission policy for an automatic application.
- Automatic submission uses saved answers and factual templates, checks live eligibility, and re-checks
  the enabled policy immediately before sending. Manual applications still require individual approval.
- Any change after approval cancels it.
- One approval can drive at most one submission; duplicates are blocked in the database transaction.
- An interrupted or unconfirmed submission is flagged for a manual check and never retried.
- CAPTCHA, login walls and human checks are detected and handed to you. They are never bypassed.
- No email is ever sent or replied to: the Gmail scope makes that impossible.
- Consent / privacy choices require your manual answer or a saved answer to the exact same question.
  A similar question never supplies consent for a different agreement.
- Voluntary demographic questions get the "decline" option or are left empty.

## Known limits and things to decide

- **Initial password file**: `data/initial-credentials.txt` should be deleted after first sign-in.
- **Single factor**: there is no second factor. Keeping the dashboard on Tailscale (or behind a tunnel) is the compensating control. Add 2FA before any public exposure (see ROADMAP).
- **CSP allows inline scripts/styles**: required by the static Next.js export. All content is rendered through React (escaped); no user HTML is injected.
- **Rate limiter is in-memory**: it resets when the API restarts. Fine for a single-user private deployment; add nginx `limit_req` for public exposure (template provided).
- **Backups are local**: a disk loss loses them too.
- **The server user can read everything**: anyone with shell access as this user (or root) can read the database and CVs.

## Checks run on this deployment

Unauthenticated access to all 18 protected endpoint groups returns 401; CSRF-less writes return 403;
sign-in rate limit triggers at the 7th attempt; `/docs`, `/openapi.json`, `/.env`, `/data/sonic.db`
and path-traversal URLs return 404; port 8790 is unreachable from the public and tailnet addresses;
secret values do not appear in API responses or in tracked files.
