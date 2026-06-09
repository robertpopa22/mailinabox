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

## Arhitectura addon — OVERLAY pe zone (NU feature branches)

> ⚠ Vechiul model „feature branches" (`feature/external-dns`, `feature/rspamd-*`, etc.) e **ABANDONAT** — edita inline upstream → conflict la fiecare upgrade. Acele branch-uri NU mai exista in origin. Modelul curent = **overlay pe zone**, traieste in `management/geseidl_edition/` + `setup/geseidl_edition/`. Sursa de adevar: [`management/geseidl_edition/OVERLAY.md`](management/geseidl_edition/OVERLAY.md).

**Stare verificata 2026-06-09**: `main` = `upstream/main` + **40 commits geseidl** (3 in urma upstream/main, upstream tag curent **v76**, baza fork **v75** — gap trivial, merge curat). Manifest live (`/root/mailinabox/.geseidl-edition` = repo) → `overlay_version: 0.9.0`, **toate 6 zone active**.

| Zona | Continut | Tip | Versiune |
|------|----------|-----|----------|
| **status** | badge versiune fork; NS/glue/resolve/MX/DNSSEC/MTA-STS re-verificate pe DNS PUBLIC (1.1.1.1/8.8.8.8) + site-live HTTP + Spamhaus DQS + backup extern. NU mascheaza orb — re-verifica realitatea | runtime | v0.2.0 |
| **dns** | resolver → `127.0.0.1` (bind9) + spamhaus exception zones, idempotent + verify/rollback | provisioning | v0.2.0 |
| **ssl** | cert-provisioning resolve-check pe DNS public (patch idempotent) | provisioning | v0.4.0 |
| **mail** | arhiva email (`always_bcc` din settings.yaml) + **restrictie IMAP per-cont la source IP** (Dovecot `allow_nets`, tabel sidecar `geseidl_imap_restrictions` + CLI `imap_restrict.py`) | provisioning | v0.5.0 / v0.9.0 |
| **web** | webmail per-domeniu `mail.<domeniu>/mail/` + branding HTTP_HOST, patch-uri idempotente | provisioning | v0.6.0 |
| **spam** | rspamd: fisiere fork-tracked (`setup/rspamd.sh` 446l + UI `system-spam.html`) + 4 patch-uri integrare (mail-postfix/spamassassin/daemon-api/index), signature-gate, dry-run+revert | provisioning + runtime | v0.8.0 |

**Workflow upgrade upstream** (cand OS-ul permite setup — vezi blocaj 24.04 mai jos):
```bash
git fetch upstream && git merge upstream/main                    # conflicte doar pe blocuri marcate GESEIDL (mici)
python3 management/geseidl_edition/apply_overlay.py apply         # reinsereaza hook-uri runtime (idempotent)
sudo bash setup/geseidl_edition/apply_setup_overlay.sh           # reaplica zone provisioning (idempotent)
sudo systemctl restart mailinabox
```
`apply_overlay.py {status|apply|remove|selftest}`. Marker = `# >>> GESEIDL EDITION OVERLAY >>>` / `# <<< ... <<<`. Logica reala traieste EXCLUSIV in `geseidl_edition/`, niciodata in corpul functiilor upstream.

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

## Securitate — model pe 3 straturi (status 2026-06-09, verificat live)

> Raspuns la „suntem in siguranta cu toate elementele?" — **partial**. Cele 3 straturi NU sunt acoperite egal:

| Strat | Componente | Mecanism update | Status |
|-------|-----------|-----------------|--------|
| **1. OS base** | kernel, glibc, openssl, systemd, pachete apt | `unattended-upgrades` ACTIV + `daily-reboot.timer` 02:30 | ✅ **la zi** (0 security pending, verificat) |
| **2. MiaB app-layer** | template-uri Postfix/Dovecot/nginx, fail2ban jails, rspamd ruleset, config-uri MiaB-managed | `setup/*.sh` la `sudo mailinabox` | ⚠ **INGHETAT** — setup blocat pe 24.04 (vezi sus). Config-urile NU se reaplica. **Exceptie: certuri LE se reinnoiesc** via `daily_tasks.sh` (cron 01:07, independent de setup) — cert principal expira 21-Aug-2026, auto-renew ~iulie ✅ |
| **3. App stack (Nextcloud)** | Nextcloud + apps + PHP runtime | manual (`occ upgrade` / `nextcloud.sh` standalone) | 🔴 **STALE — risc real** |

**Stratul 3 = singurul risc de securitate efectiv si actionabil acum:**
- **Nextcloud 26.0.13** — linia 26 e **EOL din 31-mar-2024** (~2 ani fara patch-uri upstream). CVE-uri NC nepatch-uite = vector real (acces contacte/calendar CalDAV/CardDAV, potential RCE → foothold pe mail server).
- **PHP 8.0.30** — EOL upstream 26-nov-2023; patch-uit DOAR prin `ondrej/php` PPA (dependenta de 1 maintainer tert). NC nu poate urca fara PHP nou (8.1→8.2) = bottleneck.

**DECUPLARE cheie**: upgrade-ul Nextcloud e **separabil** de problema OS 24.04. Se face standalone (`bash setup/nextcloud.sh` cu versiune pinata noua + bump PHP), FARA re-run `mailinabox`. Deci stratul 3 se poate remedia pe box-ul curent, independent de decizia strategica OS.

**Lant upgrade NC** (fiecare treapta = `occ upgrade`, posibil bump PHP): 26 → 27 → 28 → 29 (→ 30/31). NU se sare versiune majora. Backup `owncloud.db` + `config.php` inainte de FIECARE treapta (vezi runbook recuperare jos).

### Decizie strategica OS (pending aprobare user — NU executa)

Upstream MiaB = **22.04-only confirmat** (preflight v76 hard-codeaza `VERSION_ID==22.04`, niciun roadmap 24.04). Optiuni:

| Opt | Descriere | Pro | Contra |
|-----|-----------|-----|--------|
| **A. Patch preflight → 24.04** | 1-line guard geseidl care accepta 24.04 → setup re-ruleaza → strat 2 dezghetat | ieftin, rapid, pastreaza OS curent | **snowflake** — `setup/*.sh` scrise/testate pt pachete 22.04; pe 24.04 (PHP 8.3 default, versiuni Dovecot/Postfix diferite) setup poate strica. De ce upstream guardeaza. Risc pe productie |
| **B. Blue-green rebuild pe 22.04** | box nou 22.04 curat → fork geseidl-edition → migrare backup/restore MiaB → cutover DNS | suportat oficial, valideaza DR, overlay-ul ride-uieste upstream cum e proiectat | scump (VM nou + fereastra cutover); 22.04 standard support → apr-2027 (runway ~10 luni → posibil alt migrate curand) |
| **C. Status-quo + mentenanta manuala** | per-componenta (ca recovery NC 2026-06-09) | zero efort acum | fragil; strat 2 ramane inghetat indefinit |

**Recomandare (Gemini xhigh + verificare la sursa):** **B pe termen lung** (revine pe sine suportate), DAR **stratul 3 (NC) se ataca ACUM independent** (opt A-light doar pt `nextcloud.sh`, fara setup complet) fiindca e singurul risc activ. Decizia A/B/C = a user-ului.

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
