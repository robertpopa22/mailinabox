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

ZONE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
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

# --- 3) Interzicere redirect din sieve utilizatori (WS3, 2026-08-17) ---------
# Politica: forwardarile se fac DOAR prin aliasuri administrate (panoul admin).
# sieve_max_redirects=0 dezactiveaza actiunea `redirect` in TOATE scripturile
# sieve (utilizator + ManageSieve refuza la upload scripturi cu redirect).
# Filtrele de sortare (fileinto), vacation etc. raman functionale.
apply_sieve_no_redirect() {
	local CONF=/etc/dovecot/conf.d/99-zz-geseidl-sieve.conf
	local WANT
	WANT=$(cat <<'EOF'
plugin {
  # Geseidl Edition (WS3 2026-08-17): redirect interzis din filtrele
  # utilizatorului; forwardari doar prin aliasuri administrate de IT.
  sieve_max_redirects = 0
}
EOF
)
	if [ -f "$CONF" ] && [ "$(cat "$CONF")" = "$WANT" ]; then
		log "sieve_max_redirects=0 deja aplicat. skip."
		return 0
	fi
	printf '%s\n' "$WANT" > "$CONF"
	systemctl reload dovecot 2>/dev/null || doveadm reload || true
	log "sieve_max_redirects=0 aplicat ($CONF). dovecot reloaded."
}

# --- 4) Auth policy „greylist" (WS8+, 2026-08-17) ----------------------------
# Dovecot consulta serviciul local geseidl-authpolicy (127.0.0.1:8127) la fiecare
# autentificare, inclusiv cu parola corecta. Mod monitor/enforce in
# /etc/geseidl/authpolicy.conf. FAIL-OPEN: auth_policy_reject_on_fail ramane
# implicit `no` — daca serviciul pica, autentificarea continua normal.
apply_auth_policy() {
	local CONF=/etc/dovecot/conf.d/99-zz-geseidl-authpolicy.conf
	local NONCE_FILE=/etc/geseidl/authpolicy_nonce

	if ! curl -s -m 2 -o /dev/null -X POST http://127.0.0.1:8127/; then
		log "geseidl-authpolicy nu raspunde pe 8127 — NU configurez dovecot (siguranta)."
		return 0
	fi

	if [ ! -f "$NONCE_FILE" ]; then
		mkdir -p /etc/geseidl
		openssl rand -hex 16 > "$NONCE_FILE"
		chmod 600 "$NONCE_FILE"
	fi
	local NONCE
	NONCE="$(cat "$NONCE_FILE")"

	local WANT
	WANT=$(cat <<EOF
# Geseidl Edition: auth policy greylist (serviciu local geseidl-authpolicy).
auth_policy_server_url = http://127.0.0.1:8127/
auth_policy_hash_nonce = $NONCE
auth_policy_check_before_auth = yes
auth_policy_check_after_auth = yes
auth_policy_report_after_auth = yes
auth_policy_request_attributes = login=%{requested_username} remote=%{rip} protocol=%s
EOF
)
	if [ -f "$CONF" ] && [ "$(cat "$CONF")" = "$WANT" ]; then
		log "auth_policy deja configurat. skip."
		return 0
	fi
	printf '%s\n' "$WANT" > "$CONF"
	systemctl restart dovecot
	log "auth_policy configurat ($CONF). dovecot restarted."
}

# --- 5) IP real in webmail (2026-08-17) --------------------------------------
# Dovecot accepta IP-ul original al browserului forwardat de Roundcube prin
# IMAP ID (plugin dovecot_ident, instalat de setup/webmail.sh). Astfel
# allow_nets / auth policy / logging se aplica pe vizitatorul REAL, nu pe
# 127.0.0.1 — conturile restrictionate au webmail DOAR din retele interne,
# conturile nerestrictionate (ex. clienti biamco.ro) si din exterior.
apply_webmail_real_ip() {
	local CONF=/etc/dovecot/conf.d/99-zz-geseidl-trusted.conf
	local WANT='# Geseidl Edition: Roundcube (localhost) forwardeaza IP-ul real prin IMAP ID.
login_trusted_networks = 127.0.0.1 ::1'
	local RCM_PLUG=/usr/local/lib/roundcubemail/plugins
	local RCM_CFG=/usr/local/lib/roundcubemail/config/config.inc.php

	# plugin (aplicare live, idempotenta; setup/webmail.sh il pune si el)
	if [ -d "$RCM_PLUG" ]; then
		rm -rf "$RCM_PLUG/dovecot_ident"
		cp -r /root/mailinabox/conf/roundcube-plugins/dovecot_ident "$RCM_PLUG/dovecot_ident"
		if [ -f "$RCM_CFG" ] && ! grep -q "dovecot_ident" "$RCM_CFG"; then
			sed -i "s/\(\$config\['plugins'\] = array(\)/\1'dovecot_ident', /" "$RCM_CFG"
			log "dovecot_ident adaugat in config.inc.php."
		fi
	fi

	if [ -f "$CONF" ] && [ "$(cat "$CONF")" = "$WANT" ]; then
		log "login_trusted_networks deja aplicat. skip."
		return 0
	fi
	printf '%s\n' "$WANT" > "$CONF"
	systemctl restart dovecot
	log "login_trusted_networks aplicat ($CONF). dovecot restarted."
}

# --- 6) Monitor rapoarte agregate DMARC (2026-08-31) -------------------------
# Rapoartele rua ajung in mailboxul tehnic gesit-alerte@. Serviciul local
# arhiveaza rapoartele sanatoase si notifica dit@ numai pentru DMARC fail,
# disposition reject/quarantine, policy drift sau erori declarate in raport.
apply_dmarc_alerts() {
	local SCRIPT_SRC="$ZONE_DIR/dmarc_alerts.py"
	local SCRIPT_DST=/usr/local/libexec/geseidl-dmarc-alerts
	local SERVICE=geseidl-dmarc-alerts.service
	local TIMER=geseidl-dmarc-alerts.timer

	if [ ! -f "$SCRIPT_SRC" ]; then
		log "EROARE: sursa monitorului DMARC lipseste ($SCRIPT_SRC)."
		return 1
	fi
	if ! sqlite3 "$USERS_DB" "SELECT 1 FROM users WHERE email='gesit-alerte@geseidl.ro' LIMIT 1;" | grep -qx 1; then
		log "EROARE: mailboxul gesit-alerte@geseidl.ro nu exista; monitorul ramane neinstalat."
		return 1
	fi

	install -d -o root -g root -m 0755 /usr/local/libexec || return 1
	install -d -o root -g root -m 0700 /var/lib/geseidl-dmarc-alerts || return 1
	install -o root -g root -m 0755 "$SCRIPT_SRC" "$SCRIPT_DST" || return 1
	install -o root -g root -m 0644 "$ZONE_DIR/$SERVICE" "/etc/systemd/system/$SERVICE" || return 1
	install -o root -g root -m 0644 "$ZONE_DIR/$TIMER" "/etc/systemd/system/$TIMER" || return 1

	"$SCRIPT_DST" --self-test >/dev/null || return 1
	doveadm mailbox create -u gesit-alerte@geseidl.ro Archive 2>/dev/null || true
	doveadm mailbox create -u gesit-alerte@geseidl.ro Invalid 2>/dev/null || true
	systemctl daemon-reload || return 1
	systemctl enable --now "$TIMER" >/dev/null || return 1
	log "monitor DMARC instalat; timer 15 minute, notificare doar la probleme."
}

# --- 7) fail2ban: filtru Dovecot corectat + praguri Geseidl (2026-09-13) ------
# Filtrul upstream `dovecotimap` nu matcheaza formatul Dovecot 2.3.21
# (`Disconnected: Connection closed (auth failed`) -> jail orb. Sursa filtrului
# corectat = conf/fail2ban/filter.d/dovecotimap.conf (instalat si de setup/system.sh);
# pragurile = fail2ban-zz-geseidl.conf din aceasta zona -> jail.d/zz-geseidl.conf
# (fisier separat de mailinabox.conf, care e regenerat la fiecare setup).
apply_fail2ban_geseidl() {
	local REPO_ROOT FILTER_SRC FILTER_DST JAIL_SRC JAIL_DST changed=0
	REPO_ROOT="$(cd "$ZONE_DIR/../../../.." && pwd)"
	FILTER_SRC="$REPO_ROOT/conf/fail2ban/filter.d/dovecotimap.conf"
	FILTER_DST=/etc/fail2ban/filter.d/dovecotimap.conf
	JAIL_SRC="$ZONE_DIR/fail2ban-zz-geseidl.conf"
	JAIL_DST=/etc/fail2ban/jail.d/zz-geseidl.conf
	for pair in "$FILTER_SRC:$FILTER_DST" "$JAIL_SRC:$JAIL_DST"; do
		local src="${pair%%:*}" dst="${pair##*:}"
		[ -f "$src" ] || { log "EROARE: lipseste $src"; return 1; }
		if ! cmp -s "$src" "$dst"; then
			install -m 0644 "$src" "$dst"
			changed=1
		fi
	done
	if [ "$changed" = 0 ]; then
		log "fail2ban (filtru dovecotimap + praguri Geseidl) deja aplicat. skip."
		return 0
	fi
	# Gard: nu incarcam o configuratie care nu trece testul de sintaxa.
	if ! fail2ban-client -t >/dev/null 2>&1; then
		log "EROARE: fail2ban-client -t a esuat; configuratia NU a fost reincarcata."
		return 1
	fi
	fail2ban-client reload >/dev/null 2>&1 || systemctl restart fail2ban
	log "fail2ban reincarcat: filtru dovecotimap corectat + jail.d/zz-geseidl.conf."
}

apply_archive_bcc
apply_imap_allow_nets
apply_sieve_no_redirect
apply_auth_policy
apply_webmail_real_ip
apply_fail2ban_geseidl || {
	log "EROARE: configurarea fail2ban a esuat; zona mail este incompleta."
	exit 1
}
apply_dmarc_alerts || {
	log "EROARE: instalarea monitorului DMARC a esuat; zona mail este incompleta."
	exit 1
}
log "zona mail gata."
