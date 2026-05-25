#!/bin/bash
# Geseidl Edition — zona dns (provisioning).
#
# Aliniaza resolverul box-ului la designul MiaB: /etc/resolv.conf -> 127.0.0.1
# (bind9 local), + zone-exception spamhaus.org/dbl.spamhaus.org ca interogarile
# RBL sa fie rezolvate prin recursie DIRECTA (nu prin forwarders = shared resolver,
# care intoarce 127.255.255.254). Fara asta, check-ul spamhaus din status iese `?`.
#
# Idempotent: daca e deja aplicat, nu face nimic.
# Cu plasa de siguranta: daca rezolutia se rupe dupa flip, ROLLBACK automat.
#
# Rulat de: setup/geseidl_edition/apply_setup_overlay.sh (sau manual ca root).
set -uo pipefail

MARK_START="# >>> GESEIDL dns zone >>>"
MARK_END="# <<< GESEIDL dns zone <<<"
NAMED_LOCAL="/etc/bind/named.conf.local"
RESOLVED_CONF="/etc/systemd/resolved.conf"

log() { echo "[geseidl/dns] $*"; }

# --- idempotenta ---
already_resolver=0
if [ -f /etc/resolv.conf ] && ! [ -L /etc/resolv.conf ] && grep -q "^nameserver 127.0.0.1" /etc/resolv.conf; then
	already_resolver=1
fi
already_spamhaus=0
# zonele de exceptie pot fi in named.conf.local SAU intr-un include (named.conf.spamhaus)
if grep -rq "spamhaus.org" /etc/bind/ 2>/dev/null; then
	already_spamhaus=1
fi
if [ "$already_resolver" = 1 ] && [ "$already_spamhaus" = 1 ]; then
	log "deja aplicat (resolver=127.0.0.1, spamhaus zones prezente). skip."
	exit 0
fi

# --- backup ---
BK="/root/geseidl-dns-flip-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BK"
ls -la /etc/resolv.conf > "$BK/resolv.symlink.txt" 2>&1 || true
cp -L /etc/resolv.conf "$BK/resolv.conf.orig" 2>/dev/null || true
cp "$NAMED_LOCAL" "$BK/named.conf.local.orig" 2>/dev/null || true
cp "$RESOLVED_CONF" "$BK/resolved.conf.orig" 2>/dev/null || true
resolvectl status > "$BK/resolvectl.pre.txt" 2>&1 || true
log "backup in $BK"

rollback() {
	log "!!! ROLLBACK"
	cp "$BK/named.conf.local.orig" "$NAMED_LOCAL" 2>/dev/null || true
	cp "$BK/resolved.conf.orig" "$RESOLVED_CONF" 2>/dev/null || true
	rm -f /etc/resolv.conf
	ln -sf ../run/systemd/resolve/stub-resolv.conf /etc/resolv.conf
	systemctl restart systemd-resolved 2>/dev/null || true
	systemctl restart bind9 2>/dev/null || true
	log "rollback complet. stare originala restaurata din $BK"
}

# --- 1. spamhaus exception zones (doar daca bind9 are forwarders) ---
if [ "$already_spamhaus" = 0 ] && grep -q "forwarders" /etc/bind/named.conf.options 2>/dev/null; then
	{
		echo ""
		echo "$MARK_START"
		echo "# Rezolva spamhaus.org direct (ocoleste forwarders) -> RBL valid."
		echo 'zone "spamhaus.org" { type forward; forward only; forwarders { }; };'
		echo 'zone "dbl.spamhaus.org" { type forward; forward only; forwarders { }; };'
		echo "$MARK_END"
	} >> "$NAMED_LOCAL"
	log "adaugat spamhaus exception zones"
fi

# valideaza configul bind INAINTE de a atinge resolverul
if ! named-checkconf; then
	log "named-checkconf a esuat — revin named.conf.local si abort (resolver neatins)"
	cp "$BK/named.conf.local.orig" "$NAMED_LOCAL" 2>/dev/null || true
	exit 1
fi

# --- 2. flip resolver la 127.0.0.1 (varianta MiaB) ---
if [ "$already_resolver" = 0 ]; then
	rm -f /etc/resolv.conf
	if grep -qiE '^[#[:space:]]*DNSStubListener' "$RESOLVED_CONF"; then
		sed -i 's/^[#[:space:]]*DNSStubListener=.*/DNSStubListener=no/I' "$RESOLVED_CONF"
	else
		echo "DNSStubListener=no" >> "$RESOLVED_CONF"
	fi
	printf 'nameserver 127.0.0.1\nsearch .\n' > /etc/resolv.conf
	log "resolv.conf -> 127.0.0.1, DNSStubListener=no"
fi

# --- 3. restart servicii ---
systemctl restart bind9
systemctl restart systemd-resolved
sleep 2

# --- 4. verificare + auto-rollback ---
EXT=$(dig +short +time=4 +tries=2 @127.0.0.1 gmail.com MX | head -1)
SELF=$(dig +short +time=4 +tries=2 @127.0.0.1 mail.geseidl.ro A | head -1)
SPAM=$(dig +short +time=6 +tries=1 @127.0.0.1 2.0.0.127.zen.spamhaus.org A | head -1)
log "verify: gmail MX='$EXT' | mail.geseidl.ro='$SELF' | spamhaus-test='$SPAM'"

if [ -z "$EXT" ] || [ -z "$SELF" ]; then
	log "rezolutie de baza RUPTA dupa flip"
	rollback
	exit 1
fi

case "$SPAM" in
	127.255.255.254|"") log "ATENTIE: spamhaus inca raspunde shared/empty ('$SPAM') — verifica manual (poate cache)";;
	127.0.0.*) log "spamhaus RBL OK (raspuns test $SPAM)";;
	*) log "spamhaus raspuns neasteptat: $SPAM";;
esac

log "GATA. resolver=127.0.0.1, spamhaus zones active. backup: $BK"
