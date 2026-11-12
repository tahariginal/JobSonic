# Host JobSonic: backend on the Oracle VM, dashboard on Vercel

This file is a task for a Claude Code session running on **sonic's own computer** (for example a 1337
session), started with the Chrome extension. That session can do two things the VM cannot: reach the
VM through the `sonic` script, and use sonic's signed-in browser to create the Vercel project.

## For the human (sonic)

Before you start, check that:

- the `sonic` script on this computer opens a shell on the Oracle VM,
- Chrome is open with the Claude extension, and you are signed in to **vercel.com** with your GitHub account.

Then run:

```bash
git clone https://github.com/tahariginal/JobSonic.git   # or `git pull` if you already have it
cd JobSonic
claude --chrome
```

and tell it: **"Read host_front_back.md and do what it says."**

At the end you sign in to the new site yourself. Claude never needs your dashboard password.

---

## Prompt (for Claude)

You are deploying **JobSonic** (also called SONIC JOBS), sonic's personal job search and application
system. You have none of the context from the session that built it, so everything you need is here.

### How it is built

| Part | Where it runs | Notes |
|---|---|---|
| Backend: FastAPI API, worker, SQLite database, headless browser | Oracle VM, already running | systemd `sonic-jobs-api` (listens on `127.0.0.1:8790` only) and `sonic-jobs-worker`. Code in `/home/ubuntu/works/sonic-jobs`. |
| Dashboard: Next.js pages in `frontend/` | Vercel (to be created) | Calls `/api/*` on its own origin. |

The backend cannot run on Vercel. The result you are building is:

```
browser -> https://<project>.vercel.app/api/*   (Vercel forwards it, so the session cookie stays same-origin)
        -> https://<api host>/api/*             (nginx on the VM, HTTPS, only /api/ is exposed)
        -> http://127.0.0.1:8790/api/*          (the backend)
```

Two pieces are already in the repository and tested on the VM:

- `deploy/enable-public-api.sh` opens the API on the VM: it adds one nginx site, gets a Let's Encrypt
  certificate, checks the result, and prints a line `API_ORIGIN=https://...`. It is safe to run again.
- `frontend/next.config.ts` switches to hosted mode when the environment variable `SONIC_API_ORIGIN`
  is set, and forwards `/api/*` to it. On Vercel the build fails on purpose if that variable is missing.

The API address is not written anywhere in this repository (the repository is public). You get it from
the script's output and give it to Vercel as an environment variable.

### Work with two agents

Use the Agent tool. Run the agents one after the other, because the second needs the first one's result.

1. **Agent "backend"**: does "Part 1" below over SSH and returns the `API_ORIGIN` value and its check results.
2. **Agent "frontend"**: does "Part 2" below in Chrome and returns the Vercel URL.
   If a subagent cannot use the Chrome tools, do Part 2 yourself in the main session instead.
3. **You (the lead)**: do "Part 3" (final checks), then write the report.

Give each agent the rules in "Rules" word for word. They do not see this file unless you pass it on.

### Part 1: open the API on the VM

**Reaching the VM.** sonic uses a script or command called `sonic` on this computer to connect to the VM.

1. Find it: `type sonic`, `command -v sonic`, then look in `~`, `~/bin`, `~/.local/bin` and the shell
   aliases. Read it before you run it. Never print, copy or move a private key.
2. Work out how to run one remote command through it. If it passes arguments to `ssh`, use
   `sonic '<command>'`. If it only opens an interactive shell, take the user, host and key options from
   it and run `ssh <same options> <user>@<host> '<command>'`.
3. If you cannot find the script or the connection is refused, stop and ask sonic. Do not guess hosts.

The VM's login shell is **fish**. Wrap every remote command as `bash -lc '<command>'` so the syntax
below works as written.

**Steps on the VM** (the user there has passwordless sudo):

```bash
cd /home/ubuntu/works/sonic-jobs
git status --short                      # expect no output
git pull --ff-only                      # the VM repo already uses HTTPS with a working login
systemctl is-active sonic-jobs-api sonic-jobs-worker      # expect: active, active
curl -s http://127.0.0.1:8790/api/health                  # expect: {"status":"ok","db":"ok",...}
./deploy/enable-public-api.sh --status                    # shows whether it is already enabled
./deploy/enable-public-api.sh                             # opens the API and prints API_ORIGIN=https://...
```

- If `git status --short` shows changes or `git pull` fails, stop and report. Do not reset, stash or
  discard anything.
- If the script stops with `ERROR:`, report its message exactly. It restores the previous nginx state
  itself. Do not edit nginx files by hand.
- Keep the `API_ORIGIN=https://...` value. Below it is called `<API_ORIGIN>`.

**Check from this computer** (not from the VM), so you know the internet can reach it:

```bash
curl -s  <API_ORIGIN>/api/health                              # expect {"status":"ok","db":"ok",...}
curl -s -o /dev/null -w '%{http_code}\n' <API_ORIGIN>/           # expect 404
curl -s -o /dev/null -w '%{http_code}\n' <API_ORIGIN>/api/profile   # expect 401
```

If the campus network blocks the request, say so and continue; Part 3 repeats the check through Vercel.

### Part 2: create the Vercel project (in Chrome)

1. Open `https://vercel.com/new`. sonic must already be signed in. If not, stop and ask sonic to sign in.
2. Import the GitHub repository **`tahariginal/JobSonic`**. If Vercel says it has no access to the
   repository, ask sonic before granting any new GitHub permission.
3. Configure the project:

   | Setting | Value |
   |---|---|
   | Project name | `jobsonic` (if taken, accept what Vercel proposes) |
   | Root Directory | `frontend` |
   | Framework Preset | Next.js (detected automatically) |
   | Build Command, Output Directory, Install Command | leave the defaults. Do **not** set the output directory to `out`. |
   | Environment variable | name `SONIC_API_ORIGIN`, value `<API_ORIGIN>` (no trailing slash), for Production and Preview |

4. Deploy and wait for the build to finish.
   - A build error that mentions `SONIC_API_ORIGIN` means the variable is missing or has a path or a
     trailing slash. Fix it under Settings → Environment Variables, then redeploy.
   - For any other build error, copy the error lines into your report and stop. Do not change code.
5. Note the production URL (for example `https://jobsonic.vercel.app`). Below it is `<DASHBOARD_URL>`.

Stay on the free Hobby plan. If Vercel shows a payment, upgrade, trial or team prompt, stop and ask sonic.

### Part 3: final checks (lead)

From the terminal on this computer:

```bash
curl -s <DASHBOARD_URL>/api/health                                   # expect {"status":"ok","db":"ok",...}
curl -s -o /dev/null -w '%{http_code}\n' <DASHBOARD_URL>/login/      # expect 200
curl -s -o /dev/null -w '%{http_code}\n' <DASHBOARD_URL>/api/profile # expect 401
```

In Chrome, open `<DASHBOARD_URL>/login/` and confirm the sign-in form is shown.

Then record the dashboard URL on the VM (it is used later for the Gmail sign-in link):

```bash
cd /home/ubuntu/works/sonic-jobs && ./deploy/enable-public-api.sh --dashboard-url <DASHBOARD_URL>
```

This restarts the two services. If it answers that a background task is running, wait five minutes and
try once more; if it still refuses, leave it and say so in the report.

Finally ask sonic to sign in at `<DASHBOARD_URL>` (username `admin`) and tell you whether the Overview
page loads with jobs in it. That sign-in is the last check, and only sonic can do it.

### Rules

- **Secrets.** Never read aloud, print or copy `/home/ubuntu/works/sonic-jobs/.env`, anything under
  `data/` (it holds the database, the CV and `initial-credentials.txt`), SSH keys or tokens. Never ask
  sonic for the dashboard password and never type it into a page.
- **Only this project.** On the VM, do not touch the other nginx sites, the Docker stack, Tailscale or
  the other folders in `/home/ubuntu/works`. On Vercel, do not open, change or delete any other project.
- **No code changes.** Do not edit, commit or push anything in this repository from this computer. If
  something in the code or the script looks wrong, describe it in the report.
- **No surprises.** Ask sonic before anything that costs money, grants a new permission, adds a custom
  domain, or makes anything else public.
- **Do not retry blindly.** If a step fails twice the same way, stop and report what you saw.

### Undo

- Close the public API: on the VM, `./deploy/enable-public-api.sh --remove`. The backend keeps running
  and stays reachable through the SSH tunnel and Tailscale.
- Remove the dashboard: delete the `jobsonic` project in Vercel (ask sonic first).

### Report format

End with a short report for sonic:

```
API origin:      <API_ORIGIN>
Dashboard URL:   <DASHBOARD_URL>
Checks:          API health (direct)      ok / failed
                 API health (via Vercel)  ok / failed
                 Login page loads         ok / failed
                 Data needs sign-in (401) ok / failed
                 Dashboard URL recorded   ok / skipped (why)
Not done / failed: <anything skipped, with the exact error text>
For sonic:       1. Sign in at <DASHBOARD_URL> with username admin and confirm the Overview loads.
                 2. Change the admin password now that the login page is public:
                    on the VM, in /home/ubuntu/works/sonic-jobs/backend, run
                    `.venv/bin/python -m app.cli create-user admin`, then delete
                    `../data/initial-credentials.txt`.
```
