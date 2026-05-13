#!/bin/bash
# Install email indexer on Mail-in-a-Box server.
# Run as root on MAIL02 (10.0.1.89).
set -euo pipefail

INSTALL_DIR=/opt/email-indexer
DATA_DIR=/var/lib/email-indexer
SRC_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "[+] Installing email indexer..."
mkdir -p "$INSTALL_DIR" "$DATA_DIR"
install -m 0755 "$SRC_DIR/indexer.py" "$INSTALL_DIR/indexer.py"
chown root:root "$DATA_DIR"
chmod 755 "$DATA_DIR"

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
echo "  python3 $INSTALL_DIR/indexer.py --stats"
