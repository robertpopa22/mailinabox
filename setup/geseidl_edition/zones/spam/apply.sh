#!/bin/bash
# Geseidl Edition — zona spam (rspamd).
#
# rspamd inlocuieste SpamAssassin. Subsistem mare (vezi README.md): installer
# setup/rspamd.sh (446 linii, fork-tracked, nu conflictueaza cu upstream) +
# integrare in mail-postfix.sh/spamassassin.sh + API/UI in daemon.py/templates.
#
# Aceasta zona NU re-provisioneaza un box deja configurat (filtru LIVE). Garda:
#   - rspamd activ + spam_filter=rspamd  -> skip (cazul productie).
#   - altfel (sistem pristine)           -> ruleaza installer-ul + integrarea.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${1:-$(cd "$HERE/../../../.." && pwd)}"
STORAGE_ROOT="${STORAGE_ROOT:-/home/user-data}"
SETTINGS="$STORAGE_ROOT/settings.yaml"

log() { echo "[geseidl/spam] $*"; }

rspamd_active=0
systemctl is-active --quiet rspamd 2>/dev/null && rspamd_active=1
sel_rspamd=0
grep -q "^spam_filter:[[:space:]]*rspamd" "$SETTINGS" 2>/dev/null && sel_rspamd=1

if [ "$rspamd_active" = 1 ] && [ "$sel_rspamd" = 1 ]; then
	log "rspamd activ + spam_filter=rspamd in settings.yaml -> deja configurat, skip."
	exit 0
fi

# Sistem pristine: reconstituie rspamd. Installer-ul e fork-tracked in setup/.
if [ -f "$REPO_ROOT/setup/rspamd.sh" ]; then
	log "rspamd neconfigurat -> rulez installer-ul (setup/rspamd.sh) + integrare."
	log "ATENTIE: integrarea mail-postfix/spamassassin/API ruleaza in cadrul setup-ului MiaB."
	# pe un box pristine, setup/start.sh + mail-*.sh apeleaza deja rspamd.sh cand
	# spam_filter=rspamd; aici doar ne asiguram ca selectia e setata.
	if [ "$sel_rspamd" = 0 ]; then
		echo "spam_filter: rspamd" >> "$SETTINGS"
		log "setat spam_filter=rspamd in settings.yaml (setup-ul va instala rspamd)."
	fi
else
	log "setup/rspamd.sh lipseste in repo — nu pot reconstitui. vezi README.md."
	exit 1
fi
