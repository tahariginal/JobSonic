# Deployment

## What is installed on this server

Server: Ubuntu 24.04 (ARM64), 2 cores, 11 GB RAM. Existing services (nginx on 80/443, Docker
stack on 3000/8003, Tailscale) were inspected and **not modified**.

| Piece | Where |
|---|---|
| Code | `/home/ubuntu/works/sonic-jobs` |
| Config and secrets | `/home/ubuntu/works/sonic-jobs/.env` (mode 600) |
| Data | `/home/ubuntu/works/sonic-jobs/data` (mode 700): `sonic.db`, `uploads/`, `screenshots/`, `backups/` |
| API + dashboard | `sonic-jobs-api.service`, uvicorn on `127.0.0.1:8790` only |
| Worker | `sonic-jobs-worker.service` |
| Backup | `sonic-jobs-backup.timer`, daily about 03:20 UTC, keeps 14 |
| Logs | journald (`journalctl -u sonic-jobs-api -u sonic-jobs-worker`), capped at 400 MB / 30 days |

Docker was not used: two small Python processes under systemd use about 115 MB RAM idle and are
simpler to operate. System changes made: package `libatomic1`, a Chromium build for Playwright in
`~/.cache/ms-playwright`, the four unit files and one journald drop-in.

Both services are enabled at boot, restart on failure, and run database migrations on start.
After a restart the worker fails any interrupted task and flags an interrupted submission for a
manual check instead of retrying it.

## Access

The dashboard listens on loopback only. It is not reachable from the internet. Choose one:

### A. Tailscale HTTPS (recommended, private, works from your phone)

This server is already on your Tailscale network as `sonic`. Tailscale Serve is not enabled for the
tailnet yet, which only you can do:

1. Open the link Tailscale prints (`https://login.tailscale.com/f/serve?node=...`) and enable Serve/HTTPS.
2. Run `./deploy/enable-tailscale-https.sh`
3. Open `https://sonic.<your-tailnet>.ts.net:8443` on any device signed in to your tailnet.

### B. SSH tunnel (works right now, laptop only)

```bash
ssh -L 8790:127.0.0.1:8790 <your-ssh-user>@<server>
# then open http://localhost:8790
```

Chrome and Firefox accept the HTTPS-only session cookie on `localhost`. Safari does not; for
Safari set `SONIC_COOKIE_SECURE=false` in `.env` and restart (only do this for tunnel use).

### C. Public HTTPS through the existing nginx (your decision)

Template: `deploy/nginx-public.conf.example`. Authentication, CSRF protection, rate limiting and
security headers are in place, but a private address is the safer default for a system holding
your CV and application history. Nothing was changed in nginx or DNS.

### D. Dashboard on Vercel, API on this server (public, your decision)

The pages are hosted by Vercel and `/api/*` is forwarded to this server, so the backend, database
and worker stay here. Only `/api/` is exposed, behind HTTPS and the sign-in.

1. On this server: `./deploy/enable-public-api.sh` (adds one nginx site and a certificate, then
   prints `API_ORIGIN=https://...`). `--status` shows it, `--remove` closes it again.
2. In Vercel: import the repository with Root Directory `frontend` and the environment variable
   `SONIC_API_ORIGIN` set to that value.
3. `./deploy/enable-public-api.sh --dashboard-url https://<project>.vercel.app`

`host_front_back.md` at the repository root is a ready prompt that makes a Claude Code session on
your own computer do these steps. The login page becomes public, so keep the password long and random.

## First sign-in

Username `admin`. The generated password is in `data/initial-credentials.txt` (owner-only).
Read it, sign in, then delete the file. To set your own password:

```bash
cd backend && .venv/bin/python -m app.cli create-user admin
```

## Configuration (`.env`)

| Variable | Meaning |
|---|---|
| `SONIC_PORT`, `SONIC_HOST` | Bind address. Keep `127.0.0.1`. |
| `SONIC_COOKIE_SECURE` | `true` = session cookie only over HTTPS (or localhost). |
| `SONIC_PUBLIC_BASE_URL` | HTTPS address of the dashboard. Required for the Gmail OAuth redirect. |
| `SONIC_AI_MODE` | `off` (default) or `claude_cli`. See `AI_COSTS.md`. |
| `SONIC_AI_MODEL` | Model alias passed to the CLI (default `haiku`). |
| `SONIC_ALLOW_REAL_SUBMIT` | `false` makes approved applications stop before the submit button. |
| `SONIC_SECRET_KEY`, `SONIC_ENCRYPTION_KEY` | Generated at install. Losing the encryption key means reconnecting Gmail/Telegram. |

Restart both services after editing `.env`. Everything else (schedule, budgets, sources,
notifications) is edited in the dashboard under Settings.

## Updating

```bash
cd /home/ubuntu/works/sonic-jobs
(cd backend && .venv/bin/pip install -r requirements.txt)
(cd frontend && npm ci && npx next build)
sudo systemctl restart sonic-jobs-api sonic-jobs-worker      # migrations run automatically
```

## Backup and restore

Backups are consistent SQLite snapshots plus uploaded documents: `data/backups/sonic-*.tar.gz`.
They stay on this server; copy them elsewhere if you want protection against losing the disk.

```bash
sudo systemctl stop sonic-jobs-api sonic-jobs-worker
tar -xzf data/backups/sonic-YYYYMMDD-HHMMSS.tar.gz -C /tmp/restore
cp /tmp/restore/sonic.db data/sonic.db && cp -r /tmp/restore/uploads/. data/uploads/
sudo systemctl start sonic-jobs-api sonic-jobs-worker
```

## Troubleshooting

| Symptom | Check |
|---|---|
| Dashboard does not load | `systemctl status sonic-jobs-api`, `curl http://127.0.0.1:8790/api/health` |
| Signed out immediately | Using plain HTTP on a non-localhost address while `SONIC_COOKIE_SECURE=true` |
| "Too many attempts" at sign-in | Six attempts per five minutes per address; wait or restart the API |
| Searches do not run | `systemctl status sonic-jobs-worker`; Activity page; Settings → Search & schedule |
| A source shows an error | Settings → Job sources shows the last status; the board may have moved ATS |
| Form filling fails | Application → Form screenshots shows the page as the agent saw it and the reason |
| Browser will not start | `backend/.venv/bin/playwright install chromium`; `libatomic1` must be installed |
| Gmail will not connect | Redirect URI in Google Cloud must equal the one shown in Settings → Email |

## Removing

```bash
sudo systemctl disable --now sonic-jobs-api sonic-jobs-worker sonic-jobs-backup.timer
sudo rm /etc/systemd/system/sonic-jobs-* /etc/systemd/journald.conf.d/sonic-jobs.conf && sudo systemctl daemon-reload
```
