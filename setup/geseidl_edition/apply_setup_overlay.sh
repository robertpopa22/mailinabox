#!/bin/bash
# Geseidl Edition — applier overlay PROVISIONING (setup-time).
#
# Rulat DUPA setup/start.sh upstream. Aplica idempotent delta-urile de config
# pentru zonele active din .geseidl-edition (spam/mail/dns/web/ssl).
# Momentan SCHELET — zonele provisioning se migreaza din feature branches.
#
# Utilizare:  sudo bash setup/geseidl_edition/apply_setup_overlay.sh
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
MARKER="$REPO_ROOT/.geseidl-edition"

if [ ! -f "$MARKER" ]; then
	echo "[geseidl] marker .geseidl-edition absent — overlay inactiv, nimic de aplicat."
	exit 0
fi

# extrage zonele active (linii '  - <zona>' din manifest, ignora comentarii)
ZONES="$(sed -n 's/^[[:space:]]*-[[:space:]]*\([a-z]*\).*/\1/p' "$MARKER" | grep -v '^$' || true)"
echo "[geseidl] zone active: ${ZONES:-(niciuna)}"

for zone in $ZONES; do
	zdir="$HERE/zones/$zone"
	applier="$zdir/apply.sh"
	if [ -f "$applier" ]; then
		echo "[geseidl] provisioning zona: $zone"
		bash "$applier" "$REPO_ROOT"
	else
		# 'status' e runtime-only (vezi management/geseidl_edition) — fara provisioning
		[ "$zone" = "status" ] || echo "[geseidl]   (zona '$zone' inca nemigrata la overlay provisioning)"
	fi
done

echo "[geseidl] gata. Restart: sudo systemctl restart mailinabox"
