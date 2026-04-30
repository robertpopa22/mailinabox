# MAIL02 Pre-upgrade Backup — 2026-04-30 13:58 EEST

Backup tarball pentru rollback configs custom inainte de upgrade Ubuntu 22.04 → 24.04 + MiaB v74-fork → v75 rebased.

## Tarball (NU in git)

- **Filename**: `mail02-configs-20260430-1358.tar.gz`
- **Size**: 39 MB (185 files)
- **SHA256**: vezi `SHA256SUMS`
- **NU comis pe git** (contine private keys: dovecot TLS, DKIM, Let's Encrypt account)
- **Locatie locala**: `D:\github\mailinabox\backup\mail02-pre-upgrade-2026-04-30\mail02-configs-20260430-1358.tar.gz`
- **Backup secundar**: Veeam B&R full backup pe GES-S01 (declansat in Faza 0)
- **Backup VM-level**: Hyper-V checkpoint declansat in Faza 2

## Continut backup (185 files)

Vezi `MANIFEST.txt` pentru lista completa. Categorii:

| Categorie | Path |
|---|---|
| Postfix | `/etc/postfix/` |
| Dovecot | `/etc/dovecot/` (incl. private/, sieve/) |
| Rspamd | `/etc/rspamd/local.d/`, `override.d/`, `forbidden_file_extensions.map` |
| Nginx | `/etc/nginx/` |
| Let's Encrypt | `/etc/letsencrypt/` (incl. accounts + live + archive) |
| MiaB conf | `/etc/mailinabox.conf` |
| Cron jobs | `/etc/cron.d/mailinabox-*`, `cron.daily/mailinabox-*`, `munin*`, `php`, `certbot` |
| Custom scripts | `/usr/local/bin/jp.py`, `naiad_dns_monitor.py`, `rspamd_learn_report.py` |
| Spam diagnostic | `/root/spam-diagnostic/` |
| Bayes DB | `/var/lib/redis/dump.rdb` |
| DKIM keys | `/home/user-data/mail/dkim/` |
| MiaB DB | `/home/user-data/mail/users.sqlite`, `aliases` |
| MiaB internal | `/home/user-data/conf/`, `ssl/` |
| systemd custom | `/etc/systemd/system/daily-reboot.{timer,service}` |
| CVE mitigation | `/etc/modprobe.d/cve-2026-31431.conf` |
| Metadata | `root-crontab`, `running-services`, `dpkg-list`, `uname`, `os-release`, `network-interfaces`, `ip-addr`, `ip-route` |

## Restore procedure

1. Boot MAIL02 (din checkpoint sau Veeam restore daca VM corupt)
2. Daca configs sterse/corupte la upgrade:
   ```bash
   # Copiaza tarball pe MAIL02
   scp mail02-configs-20260430-1358.tar.gz dit2022@mail.geseidl.ro:/tmp/
   # Extract
   sudo tar xzf /tmp/mail02-configs-20260430-1358.tar.gz -C /
   # Restart services
   sudo systemctl restart postfix dovecot rspamd nginx
   ```

## Date critice

- Postfix `main.cf` la momentul backup: include rspamd milter (`smtpd_milters = inet:127.0.0.1:11332`)
- Dovecot custom: `99-local-*.conf` (auth, sieve, imapsieve)
- Rspamd custom: brand impersonation + RO phishing rules + neural network + force_actions DMARC override pt Gmail forwards
- DKIM mail._domainkey valid → schimbarea = email-uri reverse-detected ca spoofing pana la sync DNS

## Note

- Backup-ul NU include `/home/user-data/mail/mailboxes/` (424 GB). Pentru mailboxes = checkpoint Hyper-V + Veeam.
- Backup-ul NU include `/home/user-data/owncloud/` (Nextcloud data).
- Daca rollback complet necesar: Hyper-V checkpoint (15 min RTO) sau Veeam restore (~45 min RTO).
