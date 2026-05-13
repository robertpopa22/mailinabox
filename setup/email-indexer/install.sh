#!/bin/bash
# Install email indexer on Mail-in-a-Box server.
# Run as root on MAIL02 (10.0.1.89).
#
# Prerequisite: PostgreSQL must already be installed and `/etc/mailinabox/postgres.env`
# must exist with PG_DSN_INDEXER=... (see setup/postgres/install.sh).
set -euo pipefail

INSTALL_DIR=/opt/email-indexer
SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
PG_ENV_FILE=/etc/mailinabox/postgres.env

echo "[+] Checking prerequisites..."
if [ ! -f "$PG_ENV_FILE" ]; then
  echo "[!] Missing $PG_ENV_FILE — run setup/postgres/install.sh first." >&2
  exit 1
fi
if ! grep -q '^PG_DSN_INDEXER=' "$PG_ENV_FILE"; then
  echo "[!] $PG_ENV_FILE does not define PG_DSN_INDEXER." >&2
  exit 1
fi

echo "[+] Installing python3-psycopg (psycopg 3) ..."
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3-psycopg

echo "[+] Installing email indexer..."
mkdir -p "$INSTALL_DIR"
install -m 0755 "$SRC_DIR/indexer.py" "$INSTALL_DIR/indexer.py"

echo "[+] Installing systemd units..."
for unit in email-indexer-incremental.service email-indexer-incremental.timer \
            email-indexer-full.service email-indexer-full.timer; do
  install -m 0644 "$SRC_DIR/$unit" "/etc/systemd/system/$unit"
done

systemctl daemon-reload
systemctl enable --now email-indexer-incremental.timer
systemctl enable --now email-indexer-full.timer

echo "[+] Running initial full index (background)..."
systemctl start email-indexer-full.service --no-block

echo "[+] Done."
echo
echo "Check status:"
echo "  systemctl status email-indexer-incremental.timer email-indexer-full.timer"
echo "  systemctl list-timers email-indexer-*"
echo "  journalctl -u email-indexer-incremental.service -n 50"
echo "  PG_DSN=\$(. $PG_ENV_FILE && echo \$PG_DSN_INDEXER) python3 $INSTALL_DIR/indexer.py --stats"
