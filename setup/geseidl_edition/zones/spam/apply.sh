#!/bin/bash
# Geseidl Edition — zona spam (rspamd) overlay.
#
# rspamd inlocuieste SpamAssassin. Subsistem mare (vezi README.md). Doua tipuri
# de artefacte:
#   1. FISIERE NOI (nu exista upstream, nu conflictueaza la git merge upstream):
#        setup/rspamd.sh                       (installer rspamd, 446l)
#        management/templates/system-spam.html (UI admin spam/whitelist)
#      -> raman fork-tracked in repo; aici doar verificam prezenta.
#   2. PATCH-URI peste fisiere upstream (idempotente, signature-gate + dry-run):
#        patches/mail-postfix.patch   -> content_filter SA->rspamd (milters)
#        patches/spamassassin.patch   -> source rspamd.sh + reverse-migration + whitelist
#        patches/daemon-spam-api.patch-> API /system/spam-filter + /system/spam-whitelist + rspamd UI proxy
#        patches/index-html.patch     -> nav + panou admin spam
#      (hook-ul de status din daemon.py NU e aici — il gestioneaza apply_overlay.py.)
#
# Idempotenta:
#   - signature prezenta in target -> patch deja aplicat (sau baked in fork) -> skip.
#   - box LIVE cu rspamd activ -> filtrul NU se re-provisioneaza; doar repo-ul e
#     adus la zi (patch-urile sar ca already-applied).
#
# ATENTIE: patch-urile pe setup/*.sh prind efect la urmatorul `sudo mailinabox`
# (full setup), nu doar la `systemctl restart mailinabox`.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${1:-$(cd "$HERE/../../../.." && pwd)}"
PATCHES="$HERE/patches"
STORAGE_ROOT="${STORAGE_ROOT:-/home/user-data}"
SETTINGS="$STORAGE_ROOT/settings.yaml"

log() { echo "[geseidl/spam] $*"; }

# --- 1. fisiere noi (fork-tracked) prezente? ---
for f in setup/rspamd.sh management/templates/system-spam.html; do
	if [ -f "$REPO_ROOT/$f" ]; then
		log "fisier nou prezent: $f"
	else
		log "LIPSESTE fisier nou: $f — reconstituirea rspamd e incompleta. vezi README.md."
	fi
done

# --- 2. patch-uri peste upstream (signature-gate + dry-run + syntax-check + revert) ---
# argumente: <patch-file> <target-rel> <signature> <syntax: py|bash|none>
apply_patch() {
	local patch_file="$PATCHES/$1" target="$REPO_ROOT/$2" sig="$3" stype="$4"
	if [ ! -f "$patch_file" ]; then log "patch lipsa: $1 — skip."; return 0; fi
	if [ ! -f "$target" ]; then log "target lipsa: $2 — skip."; return 0; fi
	if grep -qF "$sig" "$target" 2>/dev/null; then
		log "$2: deja aplicat (signature prezenta). skip."
		return 0
	fi
	if ! patch -p1 -d "$REPO_ROOT" --dry-run < "$patch_file" >/dev/null 2>&1; then
		log "$2: patch NU se aplica curat (context upstream schimbat?) — verifica manual."
		return 1
	fi
	patch -p1 -d "$REPO_ROOT" < "$patch_file" >/dev/null
	case "$stype" in
		py)   python3 -c 'import ast,sys; ast.parse(sys.stdin.read())' < "$target" 2>/dev/null || { log "$2: SINTAXA PY RUPTA — revert!"; patch -R -p1 -d "$REPO_ROOT" < "$patch_file" 2>/dev/null || true; return 1; } ;;
		bash) bash -n "$target" 2>/dev/null || { log "$2: SINTAXA BASH RUPTA — revert!"; patch -R -p1 -d "$REPO_ROOT" < "$patch_file" 2>/dev/null || true; return 1; } ;;
		none) : ;;
	esac
	log "$2: patch aplicat, sintaxa OK."
}

rc=0
apply_patch mail-postfix.patch    setup/mail-postfix.sh                  "inet:127.0.0.1:11332"  bash || rc=1
apply_patch spamassassin.patch    setup/spamassassin.sh                  "source setup/rspamd.sh" bash || rc=1
apply_patch daemon-spam-api.patch management/daemon.py                   "/system/spam-filter"   py   || rc=1
apply_patch index-html.patch      management/templates/index.html        "panel_spam_filter"     none || rc=1

# --- 3. selectie filtru in settings.yaml (reconstituire pristine) ---
# Pe box LIVE cu rspamd deja activ NU re-provisionam — doar ne asiguram ca
# selectia exista, ca un viitor `sudo mailinabox` sa pastreze rspamd.
rspamd_active=0; systemctl is-active --quiet rspamd 2>/dev/null && rspamd_active=1
if grep -q "^spam_filter:[[:space:]]*rspamd" "$SETTINGS" 2>/dev/null; then
	log "settings.yaml: spam_filter=rspamd deja setat."
elif [ "$rspamd_active" = 1 ]; then
	log "rspamd activ dar spam_filter nesetat in settings.yaml -> setez (selectie)."
	echo "spam_filter: rspamd" >> "$SETTINGS"
else
	log "spam_filter nesetat + rspamd inactiv (box pristine). setez spam_filter=rspamd; ruleaza 'sudo mailinabox' ca setup-ul sa instaleze rspamd."
	[ -f "$SETTINGS" ] && echo "spam_filter: rspamd" >> "$SETTINGS"
fi

if [ "$rc" = 0 ]; then
	log "zona spam OK. (patch-urile pe setup/*.sh prind efect la 'sudo mailinabox')."
else
	log "zona spam: unul sau mai multe patch-uri n-au putut fi aplicate — vezi mesajele de mai sus."
fi
exit $rc
