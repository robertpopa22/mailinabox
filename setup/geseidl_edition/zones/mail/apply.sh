#!/bin/bash
# Geseidl Edition — zona mail: arhiva email (always_bcc) persistenta.
#
# Citeste `archive_address` din settings.yaml si seteaza Postfix `always_bcc`
# (copie a TOT mailul intrat/iesit catre mailbox-ul de arhiva — compliance).
# Idempotent. Rulat de apply_setup_overlay DUPA `sudo mailinabox`, deci arhiva
# supravietuieste re-rularilor de setup (upstream nu seteaza always_bcc).
set -uo pipefail

STORAGE_ROOT="${STORAGE_ROOT:-/home/user-data}"
SETTINGS="$STORAGE_ROOT/settings.yaml"

log() { echo "[geseidl/mail] $*"; }

ADDR="$(sed -n 's/^archive_address:[[:space:]]*//p' "$SETTINGS" 2>/dev/null | head -1)"
# strip surrounding quotes (single sau double) + spatii, fara nested-quote hell
ADDR="${ADDR%\"}"; ADDR="${ADDR#\"}"
ADDR="${ADDR%\'}"; ADDR="${ADDR#\'}"
ADDR="${ADDR%% }"; ADDR="${ADDR## }"

if [ -z "$ADDR" ]; then
	log "archive_address neconfigurata in $SETTINGS — arhiva dezactivata, skip."
	exit 0
fi

CUR="$(postconf -h always_bcc 2>/dev/null || true)"
if [ "$CUR" = "$ADDR" ]; then
	log "always_bcc deja = $ADDR. skip."
	exit 0
fi

postconf -e "always_bcc=$ADDR"
postfix reload >/dev/null 2>&1 || systemctl reload postfix
log "always_bcc -> $ADDR (postfix reloaded)."
