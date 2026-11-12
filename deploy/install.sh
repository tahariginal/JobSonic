#!/usr/bin/env bash
# Installs / updates the systemd units. Safe to re-run. Touches no other service.
set -euo pipefail
cd "$(dirname "$0")"
sudo install -m 644 sonic-jobs-api.service sonic-jobs-worker.service sonic-jobs-backup.service sonic-jobs-backup.timer /etc/systemd/system/
sudo install -d /etc/systemd/journald.conf.d
sudo install -m 644 journald-sonic-jobs.conf /etc/systemd/journald.conf.d/sonic-jobs.conf
sudo systemctl daemon-reload
sudo systemctl enable --now sonic-jobs-api.service sonic-jobs-worker.service sonic-jobs-backup.timer
sudo systemctl restart sonic-jobs-api.service sonic-jobs-worker.service
systemctl --no-pager --lines=0 status sonic-jobs-api.service sonic-jobs-worker.service | grep -E "●|Active:"
