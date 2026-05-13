#!/bin/bash
# Push live.db from MAIL02 to GES051WS workstation for MCP consumption.
# Runs after each indexer cycle (called from indexer service if SSH key present),
# OR invoke from a separate systemd path-unit.
# Requires: SSH key at /root/.ssh/ges051ws on MAIL02 + sshd on GES051WS.
#
# Alternative (recommended): GES051WS pulls via scheduled task — see sync-pull-from-mail02.ps1.
set -euo pipefail

SRC=/var/lib/email-indexer/live.db
DST_HOST="${SYNC_DST_HOST:-ges051ws.geseidl.ro}"
DST_PATH="${SYNC_DST_PATH:-/d/ArhivaEmail/email_archive_live.db}"
SSH_KEY="${SYNC_SSH_KEY:-/root/.ssh/ges051ws}"

if [[ ! -f "$SRC" ]]; then
  echo "[!] $SRC not found, skipping sync"
  exit 0
fi

rsync -az --partial \
  -e "ssh -i $SSH_KEY -o StrictHostKeyChecking=accept-new" \
  "$SRC" "${DST_HOST}:${DST_PATH}"
