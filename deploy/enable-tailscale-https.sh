#!/usr/bin/env bash
# Private HTTPS access over your Tailscale network (recommended for phone approvals).
# Prerequisite (one click, by you): enable "Serve"/HTTPS for the tailnet at the URL Tailscale prints
# the first time, e.g. https://login.tailscale.com/f/serve?node=...
set -euo pipefail
PORT_HTTPS="${1:-8443}"
ENV_FILE="$(cd "$(dirname "$0")/.." && pwd)/.env"
sudo timeout 20 tailscale serve --bg --https="${PORT_HTTPS}" http://127.0.0.1:8790 || {
  echo "Tailscale Serve is not enabled for this tailnet yet. Open the URL shown above, enable it, then re-run this script."; exit 1; }
HOST="$(sudo tailscale status --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))')"
URL="https://${HOST}:${PORT_HTTPS}"
sed -i "s|^SONIC_PUBLIC_BASE_URL=.*|SONIC_PUBLIC_BASE_URL=${URL}|; s|^SONIC_COOKIE_SECURE=.*|SONIC_COOKIE_SECURE=true|" "${ENV_FILE}"
sudo systemctl restart sonic-jobs-api sonic-jobs-worker
echo "Dashboard: ${URL}  (reachable only from devices signed in to your Tailscale network)"
