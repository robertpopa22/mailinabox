#!/bin/bash
# backup-mail-configs.sh
# Creates a tarball of all critical configs of a Mail-in-a-Box server.
# Use it BEFORE any major upgrade or impactful change.
#
# Usage:
#   sudo bash backup-mail-configs.sh
#   # OR remote:
#   ssh root@mail.example.com 'bash -s' < backup-mail-configs.sh
#
# Output: /tmp/mail-configs-YYYYMMDD-HHMM.tar.gz
#
# WARNING: tarball contains PRIVATE KEYS (TLS, DKIM, Let's Encrypt account).
# DO NOT commit to public git. Keep it locally or in a private repo.

set -e

if [[ $EUID -ne 0 ]]; then
    echo "ERROR: Run as root (sudo bash $0)"
    exit 1
fi

OUT=/tmp/mail-configs-$(hostname -s)-$(date +%Y%m%d-%H%M).tar.gz
WORK=/tmp/mail-bk-$$
mkdir -p "$WORK"

LIST="$WORK/list"
cat > "$LIST" <<'EOF'
/etc/postfix
/etc/dovecot
/etc/rspamd/local.d
/etc/rspamd/override.d
/etc/rspamd/forbidden_file_extensions.map
/etc/nginx
/etc/letsencrypt
/etc/mailinabox.conf
/etc/cron.d/mailinabox-nightly
/etc/cron.d/mailinabox-nextcloud
/etc/cron.d/munin
/etc/cron.d/munin-node
/etc/cron.d/php
/etc/cron.d/certbot
/etc/cron.daily/mailinabox-dnssec
/etc/cron.daily/mailinabox-postgrey-whitelist
/etc/cron.daily/mailinabox-ssl-cleanup
/etc/cron.daily/spamassassin
/etc/fail2ban/jail.local
/etc/fail2ban/jail.d
/etc/systemd/system/daily-reboot.timer
/etc/systemd/system/daily-reboot.service
/etc/systemd/system/weekly-reboot.timer
/etc/systemd/system/weekly-reboot.service
/etc/modprobe.d
/usr/local/bin/jp.py
/usr/local/bin/naiad_dns_monitor.py
/usr/local/bin/rspamd_learn_report.py
/root/spam-diagnostic
/root/.bashrc
/root/.profile
/var/lib/redis/dump.rdb
/home/user-data/mail/dkim
/home/user-data/mail/users.sqlite
/home/user-data/mail/aliases
/home/user-data/conf
/home/user-data/ssl
EOF

# Add metadata
crontab -l 2>/dev/null > "$WORK/root-crontab" || echo "(empty)" > "$WORK/root-crontab"
systemctl list-units --type=service --state=running --no-pager > "$WORK/running-services" 2>/dev/null
dpkg -l > "$WORK/dpkg-list" 2>/dev/null
uname -a > "$WORK/uname"
lsb_release -a > "$WORK/lsb_release" 2>/dev/null
cat /etc/os-release > "$WORK/os-release"
ip addr > "$WORK/ip-addr"
ip route > "$WORK/ip-route"

EXISTING="$WORK/existing"
> "$EXISTING"
while IFS= read -r p; do
    [ -e "$p" ] && echo "$p" >> "$EXISTING"
done < "$LIST"

for f in root-crontab running-services dpkg-list uname lsb_release os-release ip-addr ip-route; do
    [ -f "$WORK/$f" ] && echo "$WORK/$f" >> "$EXISTING"
done

tar czf "$OUT" --files-from="$EXISTING" 2>/tmp/mail-backup-errors.log

sz=$(du -h "$OUT" | awk '{print $1}')
files=$(tar tzf "$OUT" | wc -l)
sha=$(sha256sum "$OUT" | awk '{print $1}')

echo
echo "==============================================="
echo "  BACKUP COMPLETE"
echo "==============================================="
echo "  File:    $OUT"
echo "  Size:    $sz"
echo "  Files:   $files"
echo "  SHA256:  $sha"
echo
if [ -s /tmp/mail-backup-errors.log ]; then
    echo "WARNINGS (see /tmp/mail-backup-errors.log):"
    head -5 /tmp/mail-backup-errors.log
fi

rm -rf "$WORK"

echo
echo "NEXT STEP: download locally + verify integrity."
echo "  scp root@$(hostname -f):$OUT ./"
echo "  sha256sum -c <(echo \"$sha  $(basename $OUT)\")"
echo
echo "WARNING: the tarball contains PRIVATE KEYS."
echo "         Do not commit to public repos."
