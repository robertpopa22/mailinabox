#!/bin/bash
# Geseidl Edition — zona mail. Doua sub-functii idempotente, rulate de
# apply_setup_overlay DUPA `sudo mailinabox` (deci supravietuiesc re-rularilor de setup):
#
#   1) arhiva email (always_bcc) — copie a TOT mailul intrat/iesit catre mailbox-ul
#      de arhiva (compliance). Sursa: `archive_address` din settings.yaml.
#
#   2) restrictie acces IMAP/POP/Submission per-cont la source IP, via Dovecot
#      `allow_nets` (passdb extra field, verificat la autentificare). Conturi
#      precum archive@/arhive-history@ trebuie accesate doar din LAN + VPN, desi
#      box-ul e public-facing. Sursa de adevar = tabel sidecar in users.sqlite
#      (inclus automat in backup MiaB). Gestiune conturi:
#        management/geseidl_edition/imap_restrict.py {list|add|remove}
set -uo pipefail

STORAGE_ROOT="${STORAGE_ROOT:-/home/user-data}"
SETTINGS="$STORAGE_ROOT/settings.yaml"
USERS_DB="$STORAGE_ROOT/mail/users.sqlite"
DOVECOT_SQL="/etc/dovecot/dovecot-sql.conf.ext"

log() { echo "[geseidl/mail] $*"; }

# --- 1) Arhiva email (always_bcc) -------------------------------------------
apply_archive_bcc() {
	local ADDR CUR
	ADDR="$(sed -n 's/^archive_address:[[:space:]]*//p' "$SETTINGS" 2>/dev/null | head -1)"
	# strip surrounding quotes (single sau double) + spatii
	ADDR="${ADDR%\"}"; ADDR="${ADDR#\"}"
	ADDR="${ADDR%\'}"; ADDR="${ADDR#\'}"
	ADDR="${ADDR%% }"; ADDR="${ADDR## }"

	if [ -z "$ADDR" ]; then
		log "archive_address neconfigurata in $SETTINGS — arhiva dezactivata, skip."
		return 0
	fi

	CUR="$(postconf -h always_bcc 2>/dev/null || true)"
	if [ "$CUR" = "$ADDR" ]; then
		log "always_bcc deja = $ADDR. skip."
		return 0
	fi

	postconf -e "always_bcc=$ADDR"
	postfix reload >/dev/null 2>&1 || systemctl reload postfix
	log "always_bcc -> $ADDR (postfix reloaded)."
}

# --- 2) Restrictie IMAP per-cont la source IP (Dovecot allow_nets) -----------
# Tabel sidecar (sursa de adevar) + password_query Dovecot extins cu LEFT JOIN.
# Useri FARA rand in tabel => allow_nets = NULL => fara restrictie (Dovecot
# ignora field-urile extra NULL). Useri CU rand => login permis DOAR de la
# retelele listate. Folosim NULL prin LEFT JOIN (nu empty-string) ca sa nu
# blocam accidental userii nerestrictionati.
apply_imap_allow_nets() {
	if [ ! -f "$USERS_DB" ]; then
		log "users.sqlite absent ($USERS_DB) — skip allow_nets."
		return 0
	fi

	# tabel sidecar (idempotent; NU clobbereaza randuri existente -> modificarile CLI persista)
	if ! sqlite3 "$USERS_DB" \
		"CREATE TABLE IF NOT EXISTS geseidl_imap_restrictions (email TEXT PRIMARY KEY, allow_nets TEXT NOT NULL);"; then
		log "EROARE: creare tabel geseidl_imap_restrictions esuata."
		return 1
	fi

	if [ ! -f "$DOVECOT_SQL" ]; then
		log "$DOVECOT_SQL absent — skip patch password_query (Dovecot neconfigurat inca)."
		return 0
	fi

	if grep -q 'geseidl_imap_restrictions' "$DOVECOT_SQL"; then
		log "password_query deja patchuit (allow_nets). skip."
		return 0
	fi

	# rescrie linia password_query (orice forma upstream) cu varianta LEFT JOIN.
	sed -i "s|^password_query =.*|password_query = SELECT u.email AS user, u.password, r.allow_nets AS allow_nets FROM users u LEFT JOIN geseidl_imap_restrictions r ON r.email = u.email WHERE u.email='%u';|" "$DOVECOT_SQL"

	if grep -q 'geseidl_imap_restrictions' "$DOVECOT_SQL"; then
		doveadm reload >/dev/null 2>&1 || systemctl reload dovecot || true
		log "password_query -> allow_nets (LEFT JOIN). dovecot reloaded."
	else
		log "EROARE: patch password_query esuat (linia 'password_query =' negasita in $DOVECOT_SQL)."
		return 1
	fi
}

apply_archive_bcc
apply_imap_allow_nets
log "zona mail gata."
