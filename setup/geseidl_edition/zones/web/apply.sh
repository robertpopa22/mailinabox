#!/bin/bash
# Geseidl Edition — zona web (overlay patches).
#
# Webmail per-domeniu: fiecare domeniu cu conturi primeste https://mail.<domeniu>/mail/
# (Roundcube) cu cert LE propriu + branding pe HTTP_HOST. Patch-uri peste upstream:
#   webmail-subdomain.patch  -> management/{web_update,dns_update}.py
#   webmail-branding.patch   -> setup/webmail.sh
# Idempotent (skip daca semnatura e prezenta).
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${1:-$(cd "$HERE/../../../.." && pwd)}"

log() { echo "[geseidl/web] $*"; }

apply_patch() {
	local patch="$1" target="$2" sig="$3"
	if grep -qF "$sig" "$REPO_ROOT/$target" 2>/dev/null; then
		log "$patch: deja aplicat. skip."
		return 0
	fi
	if patch -p1 -d "$REPO_ROOT" --dry-run < "$HERE/$patch" >/dev/null 2>&1; then
		patch -p1 -d "$REPO_ROOT" < "$HERE/$patch"
		log "$patch: aplicat."
	else
		log "$patch: NU se aplica curat (context upstream schimbat?) — verifica manual."
		return 1
	fi
}

apply_patch webmail-subdomain.patch management/web_update.py "per-domain webmail"
apply_patch webmail-branding.patch setup/webmail.sh "HTTP_HOST"
