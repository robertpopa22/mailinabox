# mailinabox — Fork Mail-in-a-Box (geseidl-edition)

> **Parent:** [../CLAUDE.md](../CLAUDE.md) (Gestime Ecosystem — reguli universale)

---

## ⭐ DECIZIE DE BAZĂ — FORK SUVERAN (2026-06-09)

> **Plecăm pe cont propriu.** `main` (robertpopa22/mailinabox) e **baseline-ul AUTORITATIV Geseidl**, NU o oglindă a upstream.

- **NU mai facem `git merge upstream/main`.** Upstream (`mail-in-a-box/mailinabox`) devine doar un **remote de referință** din care **cherry-pick selectiv** (fix-uri securitate, features utile), evaluat manual caz-cu-caz.
- **Eliberați de constrângerile upstream:** OS (Ubuntu 24.04+), Nextcloud (versiune **suportată**), PHP (8.2/8.3) — le decidem NOI, pe ritmul nostru. Upstream rămâne deliberat blocat pe 22.04 / NC 26 / PHP 8.0; noi NU.
- **Implicație (responsabilitate):** preluăm 100% mentenanța + securitatea — nu mai vine "gratis" de la upstream. De aici **governance strict obligatoriu**: preflight propriu, verificări post-change, runbook-uri (vezi secțiunile de jos).
- **Overlay-ul `geseidl_edition/` rămâne** ca igienă (customizări modulare, izolate), dar scopul se mută de la "minimizează conflicte la merge upstream" → "ține codul nostru separat de codul moștenit din upstream".

**Consecințe concrete de execuție (sesiune nouă, cu checkpoint):**
1. Patch `setup/preflight.sh` → acceptă 24.04 (suntem suverani; nu mai e "snowflake against upstream", e baseline-ul nostru).
2. Bump `setup/nextcloud.sh` → NC versiune suportată (32/33) + `PHP_VER` 8.2/8.3.
3. Cherry-pick din upstream doar ce e relevant pt securitate/funcțional.

---

## Overview

Fork Mail-in-a-Box cu customizări pentru mediul Geseidl (NAT, DNS extern, rspamd, arhivare email).

| Aspect | Detalii |
|--------|---------|
| **Repo** | robertpopa22/mailinabox (fork upstream mail-in-a-box/mailinabox) |
| **Branch deploiat (live)** | `main` (commit 8564f8f la 2026-06-08) — NU `geseidl-edition`. Overlay-ul geseidl e cherry-picked pe main. |
| **Deploy** | MAIL02 (10.0.1.89), Hyper-V VM "GES-MAIL02" pe **GES-S11** (migrat de pe S00; copia S00 = Off) |
| **OS live** | **Ubuntu 24.04.4 LTS** — baseline-ul nostru (fork suveran). `preflight.sh` patch-uit sa accepte 24.04 (DONE 2026-06-09). |
| **PHP** | **8.2** (upgrade 2026-06-09 de pe 8.0 EOL). `PHP_VER` in `functions.sh` override-abil din env. `php8.0-fpm` dezactivat. |
| **SSH** | `ssh -i ~/.ssh/ges-mail01 dit2022@10.0.1.89` (prin `NET-ADMIN/tools/secure_connect.py --target ges-mail02 --sudo`) |
| **Resurse** | 44 vCPU, ~47 GB RAM (verificat 2026-06-09) |
| **Nextcloud** | **33.0.5** (contacts 8.5.1, calendar 6.4.2, user_external 4.0.0) — upgrade 26→33 la 2026-06-09; DB SQLite `/home/user-data/owncloud/owncloud.db`. Apps din **release-asset** (nu `/archive/`). |

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

- **Lucru pe `main`** (baseline suveran). Customizari → în `geseidl_edition/` (overlay zone), NU inline în upstream. Vezi OVERLAY.md.
- **Cherry-pick din upstream** (`mail-in-a-box/mailinabox`) selectiv, evaluat manual — NU `git merge upstream/main`.
- **Testează pe clonă** înainte de productie (MAIL02). Verifică `NET-ADMIN/GESEIDL/` pentru detalii infrastructură MAIL02.

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

**DECIS (2026-06-09) — fork suveran:** patch-uim `setup/preflight.sh` sa accepte 24.04 (e baseline-ul NOSTRU, vezi DECIZIE DE BAZĂ sus). NU rebuild pe 22.04 (upstream e blocat acolo, noi mergem inainte), NU "forward-port pe upstream care suporta 24.04" (nu exista — upstream v76 = inca 22.04-only). Testare pe clona inainte de productie fiindca `setup/*.sh` sunt testate de upstream doar pe 22.04.

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
| **2. MiaB app-layer** | template-uri Postfix/Dovecot/nginx, fail2ban jails, rspamd ruleset, config-uri MiaB-managed | `setup/*.sh` la `sudo mailinabox` | ✅ **DEZGHETAT** — `preflight` accepta 24.04; `mailinabox`/`start.sh` ruleaza din nou pe baseline-ul nostru (re-run complet 2026-06-09). Certuri LE auto-renew via `daily_tasks.sh`. |
| **3. App stack (Nextcloud)** | Nextcloud + apps + PHP runtime | `nextcloud.sh` (lant 26→33) / `occ upgrade` | ✅ **LA ZI** — NC 33.0.5 + PHP 8.2 (2026-06-09) |

**Stratul 3 — REZOLVAT 2026-06-09** (era singurul risc activ):
- **Nextcloud 26.0.13 → 33.0.5** — linia 26 era EOL mar-2024, expusa public pe `/cloud`. Acum pe linie suportata (33, suport pana ~2027). Upgrade prin lant secvential 26→27→…→33 (`setup/nextcloud.sh`).
- **PHP 8.0 → 8.2** — 8.0 era EOL nov-2023. `php8.0-fpm` dezactivat. (8.2 e deprecated in NC 33 dar suportat; bump la 8.3 = follow-up nepresant, 8.2 EOL dec-2026.)

### Decizie strategica OS + NC — REZOLVAT + EXECUTAT prin FORK SUVERAN (2026-06-09)

> Vezi "⭐ DECIZIE DE BAZĂ" (sus). Constrangerea upstream (22.04 / NC 26 / PHP 8.0) **nu ne mai leaga** — am ridicat-o.

Context verificat la sursa: upstream MiaB v76 = ÎNCĂ 22.04-only + NC 26 + PHP 8.0. Forkul nostru era identic; acum suntem suverani si l-am depasit.

**Executat (commit-uri `d54d068..fd6a9c7`):** preflight 24.04; PHP 8.0→8.2; lant `nextcloud.sh` 26→33 (SHA1 pinned, apps din release-asset); fix-uri 24.04/systemd255 (pip `--break-system-packages`, scos `systemctl link`, rspamd training non-fatal+run-once, nginx upstream php8.2). **PHP 8.2 acopera tot lantul 26→33** (single-stage). Detalii + catalog fix-uri reutilizabil: memoria `project_mailinabox_sovereign_fork` + `NET-ADMIN/GESEIDL/GES-MAIL01/GES-MAIL02.log.md` (2026-06-09 12:15).

**Follow-up nepresant:** purge pachete `php8.0*` (21, dezactivate); evaluare bump PHP 8.2→8.3; decuplare NC intr-un VM standalone (durabil — NC nu mai depinde de pin-ul MiaB).

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
