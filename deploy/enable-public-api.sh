#!/usr/bin/env bash
# Open the SONIC JOBS API to the internet over HTTPS so a dashboard hosted on Vercel can reach it.
# Only /api/ is exposed; the backend keeps listening on 127.0.0.1:8790. Safe to run again.
#
#   deploy/enable-public-api.sh                      open the API, print its address (API origin)
#   deploy/enable-public-api.sh --host <name>        same, with a hostname you chose (must resolve here)
#   deploy/enable-public-api.sh --dashboard-url <u>  record the dashboard's public URL (used for Gmail sign-in links)
#   deploy/enable-public-api.sh --status             show what is installed
#   deploy/enable-public-api.sh --remove             close it again (the certificate is kept)
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "${HERE}/.." && pwd)"
TEMPLATE="${HERE}/nginx-api-public.conf.template"
ENV_FILE="${ROOT}/.env"
SITE=/etc/nginx/sites-available/sonic-jobs-api
LINK=/etc/nginx/sites-enabled/sonic-jobs-api
WEBROOT=/var/www/certbot

say() { printf '%s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

public_ip() {
  local ip
  for url in https://api.ipify.org https://ifconfig.me/ip https://icanhazip.com; do
    ip="$(curl -4 -fsS -m 8 "$url" 2>/dev/null | tr -d '[:space:]')" || true
    if [[ "${ip}" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then printf '%s' "${ip}"; return 0; fi
  done
  return 1
}

default_host() {
  # sslip.io resolves "<anything>-<ip in hex>.sslip.io" to that IP, so no DNS setup is needed.
  local ip a b c d
  ip="$(public_ip)" || die "Could not find this server's public IP. Pass --host <name>."
  IFS=. read -r a b c d <<<"${ip}"
  printf 'jobsonic-%02x%02x%02x%02x.sslip.io' "${a}" "${b}" "${c}" "${d}"
}

installed_host() {
  [[ -f "${SITE}" ]] || return 1
  sudo sed -n 's/^[[:space:]]*server_name[[:space:]]\+\([^;]*\);.*/\1/p' "${SITE}" | head -n 1
}

render() {  # render <host> <with_tls: yes|no>
  if [[ "$2" == yes ]]; then
    sed -e "s/^#__TLS__ \{0,1\}//" -e "s/__HOST__/$1/g" "${TEMPLATE}"
  else
    sed -e "s/__HOST__/$1/g" "${TEMPLATE}"
  fi
}

install_site() {  # install_site <host> <with_tls>; restores the previous state if nginx rejects it
  local backup=""
  if [[ -f "${SITE}" ]]; then backup="$(mktemp)"; sudo cp "${SITE}" "${backup}"; fi
  render "$1" "$2" | sudo tee "${SITE}" >/dev/null
  sudo ln -sfn "${SITE}" "${LINK}"
  if ! sudo nginx -t 2>/tmp/sonic-jobs-nginx-test.log; then
    cat /tmp/sonic-jobs-nginx-test.log >&2
    if [[ -n "${backup}" ]]; then sudo cp "${backup}" "${SITE}"; else sudo rm -f "${LINK}" "${SITE}"; fi
    sudo nginx -t >/dev/null 2>&1 || true
    die "nginx rejected the new site; nothing was changed. The other sites were not touched."
  fi
  sudo systemctl reload nginx
}

cmd_status() {
  local host
  if host="$(installed_host)" && [[ -e "${LINK}" ]]; then
    say "Public API: https://${host}  (forwards /api/ to 127.0.0.1:8790)"
    curl -fsS -m 10 "https://${host}/api/health" && say "" || say "Health check through ${host} FAILED"
  else
    say "Public API: not enabled"
  fi
  grep -E '^SONIC_PUBLIC_BASE_URL=' "${ENV_FILE}" 2>/dev/null || true
}

cmd_remove() {
  sudo rm -f "${LINK}"
  sudo nginx -t
  sudo systemctl reload nginx
  say "Public API closed. The backend is reachable only on 127.0.0.1:8790 (and Tailscale, if enabled)."
}

cmd_dashboard_url() {
  local url="${1%/}"
  [[ "${url}" =~ ^https://[A-Za-z0-9.-]+(:[0-9]+)?$ ]] || die "Dashboard URL must look like https://name.vercel.app"
  [[ -f "${ENV_FILE}" ]] || die "${ENV_FILE} not found"
  # Recording the URL restarts the services, so wait if a job search or a form run is in progress.
  local running
  running="$("${ROOT}/backend/.venv/bin/python" -c "
import sqlite3
c = sqlite3.connect('file:${ROOT}/data/sonic.db?mode=ro', uri=True)
print(c.execute(\"select count(*) from tasks where status='running'\").fetchone()[0])" 2>/dev/null || echo unknown)"
  [[ "${running}" == 0 ]] || die "A background task is running (or its state is unknown: ${running}). Try again in a few minutes."
  if grep -q '^SONIC_PUBLIC_BASE_URL=' "${ENV_FILE}"; then
    sed -i "s|^SONIC_PUBLIC_BASE_URL=.*|SONIC_PUBLIC_BASE_URL=${url}|" "${ENV_FILE}"
  else
    printf 'SONIC_PUBLIC_BASE_URL=%s\n' "${url}" >>"${ENV_FILE}"
  fi
  sed -i "s|^SONIC_COOKIE_SECURE=.*|SONIC_COOKIE_SECURE=true|" "${ENV_FILE}"
  sudo systemctl restart sonic-jobs-api sonic-jobs-worker
  sleep 2
  curl -fsS -m 10 http://127.0.0.1:8790/api/health >/dev/null || die "The API did not come back after the restart."
  say "Dashboard URL recorded: ${url}"
}

cmd_enable() {
  local host="${1:-}" ip resolved
  [[ -f "${TEMPLATE}" ]] || die "Missing ${TEMPLATE}"
  command -v nginx >/dev/null || die "nginx is not installed"
  command -v certbot >/dev/null || die "certbot is not installed"
  curl -fsS -m 10 http://127.0.0.1:8790/api/health >/dev/null || die "The backend is not answering on 127.0.0.1:8790. Start it first."
  [[ -n "${host}" ]] || host="$(installed_host || true)"
  [[ -n "${host}" ]] || host="$(default_host)"
  [[ "${host}" =~ ^[a-z0-9.-]+$ ]] || die "Invalid hostname: ${host}"

  ip="$(public_ip || true)"
  resolved="$(getent ahostsv4 "${host}" | awk 'NR==1{print $1}')"
  [[ -n "${resolved}" ]] || die "${host} does not resolve."
  if [[ -n "${ip}" && "${resolved}" != "${ip}" ]]; then
    die "${host} resolves to ${resolved}, but this server's public IP is ${ip}."
  fi

  if ! sudo test -f "/etc/letsencrypt/live/${host}/fullchain.pem"; then
    say "Step 1/2: answering on port 80 and requesting a certificate for ${host}"
    sudo mkdir -p "${WEBROOT}"
    install_site "${host}" no
    sudo certbot certonly --webroot -w "${WEBROOT}" -d "${host}" --non-interactive --agree-tos --keep-until-expiring \
      || die "The certificate request failed. Port 80 must be reachable from the internet for ${host}."
  fi

  say "Step 2/2: enabling HTTPS for ${host}"
  install_site "${host}" yes

  local health code
  health="$(curl -fsS -m 15 "https://${host}/api/health" || true)"
  [[ "${health}" == *'"status":"ok"'* ]] || die "https://${host}/api/health did not answer ok. Got: ${health:-nothing}"
  code="$(curl -s -m 15 -o /dev/null -w '%{http_code}' "https://${host}/")"
  [[ "${code}" == 404 ]] || die "https://${host}/ should answer 404 (pages are not served here) but answered ${code}."
  code="$(curl -s -m 15 -o /dev/null -w '%{http_code}' "https://${host}/api/profile")"
  [[ "${code}" == 401 ]] || die "https://${host}/api/profile should need a sign-in (401) but answered ${code}."

  say ""
  say "Public API is live and checked (health ok, pages 404, data needs sign-in)."
  say "API_ORIGIN=https://${host}"
  say "Use that value for SONIC_API_ORIGIN in the Vercel project."
}

case "${1:-}" in
  --status) cmd_status ;;
  --remove) cmd_remove ;;
  --dashboard-url) [[ -n "${2:-}" ]] || die "Usage: $0 --dashboard-url https://name.vercel.app"; cmd_dashboard_url "$2" ;;
  --host) [[ -n "${2:-}" ]] || die "Usage: $0 --host <hostname>"; cmd_enable "$2" ;;
  "") cmd_enable "" ;;
  *) die "Unknown option: $1 (see the header of this file)" ;;
esac
