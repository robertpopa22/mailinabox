# mailinabox — Fork Mail-in-a-Box (geseidl-edition)

> **Parent:** [../CLAUDE.md](../CLAUDE.md) (Gestime Ecosystem — reguli universale)

---

## Overview

Fork Mail-in-a-Box cu customizări pentru mediul Geseidl (NAT, DNS extern, rspamd, arhivare email).

| Aspect | Detalii |
|--------|---------|
| **Repo** | robertpopa22/mailinabox (fork upstream mail-in-a-box/mailinabox) |
| **Branch deploiat (live)** | `main` (commit 8564f8f la 2026-06-08) — NU `geseidl-edition`. Overlay-ul geseidl e cherry-picked pe main. |
| **Deploy** | MAIL02 (10.0.1.89), Hyper-V VM "GES-MAIL02" pe **GES-S11** (migrat de pe S00; copia S00 = Off) |
| **OS live** | ⚠ **Ubuntu 24.04.4 LTS** — upstream MiaB (si acest fork) suporta DOAR 22.04. Vezi "OS 24.04 — upgrade blocat". |
| **PHP** | 8.0 (pinat pt Nextcloud; nu 8.3 din 24.04) |
| **SSH** | `ssh -i ~/.ssh/ges-mail01 dit2022@10.0.1.89` (prin `NET-ADMIN/tools/secure_connect.py --target ges-mail02 --sudo`) |
| **Resurse** | 44 vCPU, ~47 GB RAM (verificat 2026-06-09) |
| **Nextcloud** | 26.0.13 (contacts 5.5.4, calendar 4.7.20, user_external 3.4.0); DB SQLite `/home/user-data/owncloud/owncloud.db` |

---

## Feature Branches

Fiecare branch e independent, de pe `main`:

| Branch | Scop |
|--------|------|
| `feature/external-dns-settings` | Skip NS/DNSSEC/TLSA/glue/A record checks pt DNS extern (Cloudflare) |
| `feature/nat-aware-checks` | Service checks pe PRIVATE_IP când behind NAT, MTA-STS fallback localhost |
| `feature/spamhaus-forwarders-fix` | Auto zone exception pt spamhaus.org când bind9 are forwarders |
| `feature/email-archive-option` | `archive_address` în settings.yaml → `always_bcc` în Postfix |
| `feature/rspamd-spam-filter` | Înlocuire SpamAssassin cu rspamd |
| `feature/whitelist-management` | API admin whitelist/blacklist (ambele filtre) |
| `feature/rspamd-hardening` | DQS, composite rules, DMARC scoring, Lua anti-phishing |
| `feature/webmail-subdomain` | Webmail per-domeniu: `mail.<domeniu>/mail/` (Roundcube) cu cert LE propriu, auto-provizionat ca `autoconfig.`/`autodiscover.` (necesita DNS `mail.<domeniu>` A → box) |

---

## API Endpoints

| Endpoint | Scop |
|----------|------|
| `/admin/system/external-dns` | Configurare DNS extern |
| `/admin/system/nat-mode` | Configurare NAT mode |
| `/admin/system/archive` | Configurare arhivare email |
| `/admin/system/spam-filter` | Switch SA/rspamd |
| `/admin/system/spam-whitelist` | Whitelist/blacklist management |

---

## Configurare

- Settings în `$STORAGE_ROOT/settings.yaml` (citit cu `utils.load_settings(env)`)
- Env vars MiaB: `PUBLIC_IP`, `PRIVATE_IP`, `PRIMARY_HOSTNAME`, `STORAGE_ROOT` din `/etc/mailinabox.conf`
- Spamhaus DQS key: configurată pe MAIL02
- Status actual: rspamd ACTIV, SpamAssassin DEZACTIVAT

---

## Reguli

- **Testează pe MAIL02** înainte de merge în `geseidl-edition`
- Feature branches rămân independente — merge doar în `geseidl-edition`, nu între ele
- Verifică `NET-ADMIN/GESEIDL/` pentru detalii infrastructură MAIL02

---

## ⚠ OS 24.04 — `mailinabox` upgrade BLOCAT (CRITIC, descoperit 2026-06-09)

**MAIL02 ruleaza Ubuntu 24.04.4, dar `setup/preflight.sh` (linia 15) accepta DOAR `VERSION_ID == "22.04"`** → `sudo mailinabox` / `setup/start.sh` se opresc imediat:
```
Mail-in-a-Box only supports being installed on Ubuntu 22.04, sorry. You are running: ubuntu 24.04
```
Box-ul a fost upgradat OS 22.04→24.04 candva; serviciile MiaB ruleaza, dar **setup-ul nu se mai poate re-rula**.

**Raspuns la "la urmatoarea rulare de upgrade vom fi acoperiti?": NU.**
- Mecanismul normal de upgrade (`mailinabox`) e mort pe 24.04.
- `mailinabox-nightly` (cron) face DOAR backup + status, NU setup → nu actualizeaza componente.
- Update-urile apt/kernel intra prin `daily-reboot.timer` (02:30), DAR config-urile MiaB-managed (Nextcloud, rspamd, Postfix/Dovecot templates, certuri) NU se reaplica fara setup.
- **Overlay-ul geseidl NU rezolva** gap-ul OS — acopera doar zonele lui (dns/nat/archive/rspamd/webmail). Nu patch-uieste preflight.

**Optiuni strategice (decizie user — NU executa fara aprobare):**
1. **Rebuild MAIL02 pe Ubuntu 22.04** (suportat oficial) — curat, dar migrare completa (mail+NC+config).
2. **Forward-port fork la 24.04** — rebase pe versiune upstream MiaB care suporta 24.04 (v7x), re-aplica overlay. Proper long-term.
3. **Status quo + mentenanta manuala per-componenta** (ca recuperarea NC din 2026-06-09) — fragil, fiecare componenta manual.

**Recuperare/mentenanta tintita pe componenta (workaround OS guard):** scripturile `setup/<componenta>.sh` (ex. `nextcloud.sh`) NU au guard OS (doar `preflight.sh`/`start.sh` il au) → se pot rula standalone:
```bash
cd /root/mailinabox && bash setup/nextcloud.sh   # ruleaza DOAR zona nextcloud, fara preflight
```

---

## Situatii speciale — verificari OBLIGATORII post-upgrade/recuperare (governance)

> Dupa ORICE rulare `setup/*.sh`, `mailinabox`, sau recuperare componenta, verifica:

**Nextcloud (cel mai fragil):**
```bash
# status web (NU doar occ CLI — occ poate merge cand web da 503)
curl -sk -o /dev/null -w '%{http_code}\n' --resolve mail.geseidl.ro:443:127.0.0.1 https://mail.geseidl.ro/cloud/status.php   # astept 200
# config OBLIGATORIU (altfel web 503 desi occ merge):
#   'appstoreenabled' => false   (MiaB nu foloseste appstore; altfel "Cannot write into apps directory")
#   'config_is_read_only' => true (altfel "Cannot write into config directory")
sudo -u www-data php8.0 /usr/local/lib/owncloud/occ config:system:get appstoreenabled   # false
grep config_is_read_only /home/user-data/owncloud/config.php                              # true
# date intacte:
sqlite3 /home/user-data/owncloud/owncloud.db 'SELECT count(*) FROM oc_cards; SELECT count(*) FROM oc_calendarobjects;'
# fara dir-uri app duplicate (tarball versionat vs appstore): apps/ sa NU aiba contacts-X.Y.Z langa contacts
ls /usr/local/lib/owncloud/apps/ | grep -E 'contacts|calendar'
```
**fail2ban** (toate logpath-urile jail-urilor ENABLED trebuie sa existe — un logpath lipsa opreste TOT serverul fail2ban):
```bash
fail2ban-client -t && fail2ban-client status   # "configuration test is successful" + 10 jails
```
**Core mail:** `postfix check`; `doveconf -n >/dev/null`; porturi 25/465/587/993/443 LISTEN; webmail `/mail/` 200.

---

## Runbook — recuperare Nextcloud (app/config sterse) — testat 2026-06-09

Context: `find / -delete` (www-data) sterge codul app `/usr/local/lib/owncloud` + `config.php` (owned www-data). `owncloud.db` supravietuieste daca mtime <1zi.
1. **Backup DB**: `cp /home/user-data/owncloud/owncloud.db /root/owncloud.db.bak-<data>`.
2. **config.php**: restaureaza din `/home/user-data/owncloud-backup/<cea-mai-recenta>/config.php` (are instanceid REAL + secret/salt; version == DB). `instanceid` e DETERMINIST: `oc$(echo "$PRIMARY_HOSTNAME" | sha1sum | fold -w 10 | head -1)` = `ocb29ecb2ba1` pt mail.geseidl.ro (= sufixul `appdata_ocb29ecb2ba1`).
3. **LVM snapshot** safety (`NET-ADMIN/tools/lvm_snapshot.py --target ges-mail02 --create`).
4. **Reinstaleaza app**: `cd /root/mailinabox && bash setup/nextcloud.sh` (download NC pinata + `occ upgrade` pe DB existenta + re-enable contacts/calendar/user_external).
5. **Curata duplicate**: `rm -rf apps/contacts-*.*.* apps/calendar-*.*.*` (tarball-urile versionate; pastreaza `apps/contacts`, `apps/calendar`).
6. **Fix web 503**: `occ config:system:set appstoreenabled --value=false --type=boolean` + asigura `config_is_read_only => true` in config.php; `systemctl restart php8.0-fpm`.
7. **Verifica** (vezi sectiunea governance de mai sus).
