#!/bin/bash
# Geseidl Edition — zona ssl (overlay patch).
#
# Aplica peste upstream: "use public DNS for cert provisioning resolve-check"
# (get_certificates_to_provision foloseste 1.1.1.1/8.8.8.8 in loc de resolverul
# local, ca auto-renew sa nu sara domeniile in split-horizon/NAT). Vezi patch.
#
# Idempotent: daca query_public_dns e deja prezent, skip.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${1:-$(cd "$HERE/../../../.." && pwd)}"
PATCH="$HERE/ssl_certificates.patch"
TARGET="$REPO_ROOT/management/ssl_certificates.py"

log() { echo "[geseidl/ssl] $*"; }

if [ ! -f "$TARGET" ]; then
	log "lipseste $TARGET — skip."
	exit 0
fi
if grep -q "query_public_dns" "$TARGET" 2>/dev/null; then
	log "deja aplicat (query_public_dns prezent). skip."
	exit 0
fi
if ! patch -p1 -d "$REPO_ROOT" --dry-run < "$PATCH" >/dev/null 2>&1; then
	log "patch NU se aplica curat (context upstream schimbat?) — verifica manual."
	exit 1
fi
patch -p1 -d "$REPO_ROOT" < "$PATCH"
if python3 -c "import ast; ast.parse(open('$TARGET').read())" 2>/dev/null; then
	log "patch aplicat, sintaxa OK."
else
	log "SINTAXA RUPTA dupa patch — revert!"
	patch -R -p1 -d "$REPO_ROOT" < "$PATCH" 2>/dev/null || true
	exit 1
fi
