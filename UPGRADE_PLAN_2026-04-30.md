# Upgrade MAIL02 — Ubuntu 22.04 → 24.04 + MiaB v74-fork → v75 (rebased)

**Data planificata**: TBD (asteapta confirmare user)
**Server**: GES-MAIL02 (10.0.1.89, public 82.79.229.146)
**VM Hyper-V host**: GES-S00 (10.0.1.110)
**Fereastra estimata**: 2-3 ore (timeboxed; rollback daca >2h)
**Status proiect**: **EXPERIMENTAL** — daca esueaza, rollback la checkpoint Hyper-V + Veeam restore, documentat complet

---

## 1. Scope

Upgrade in-place dual:
1. **OS**: Ubuntu 22.04 LTS (jammy) → Ubuntu 24.04 LTS (noble) via `do-release-upgrade`
2. **MiaB**: fork `feature/rspamd-spam-filter` @ `1c44f31` (server) + 4 commits ahead in fork → rebase pe upstream `v75` (latest stable)
3. **Kernel**: 5.15.0-176 → 6.8.x (Ubuntu 24.04 default)

NU în scope:
- Schimbare hostname (mail.geseidl.ro ramane)
- Schimbare IP (10.0.1.89 / 82.79.229.146 ramane)
- Schimbare DNS records (Cloudflare + AD DNS unchanged)
- Schimbare VLAN / network config

---

## 2. Current State (Inventory 2026-04-30 13:30)

### OS / Kernel / Packages
- **OS**: Ubuntu 22.04.5 LTS (jammy)
- **Kernel**: 5.15.0-176-generic
- **Pachete instalate**: 1047
- **Disk /**: 784G total, 467G used (60%), **278G free** (suficient pt upgrade)
- **/home/user-data**: **424GB** (mailboxes + Nextcloud + DKIM + DNS state)

### Software stack
- **PHP**: 8.0.30 (default jammy; noble = 8.3)
- **Dovecot**: 2.3.16
- **Postfix**: detect failed (manual check needed)
- **Rspamd**: 2.7 (custom backport repo)
- **Postgres**: nedetectat la primul check (Nextcloud + MiaB nu necesita PG; SQLite default)

### MiaB version on server
- **Repo path**: `/root/mailinabox`
- **Branch**: `feature/rspamd-spam-filter` (fork)
- **HEAD**: `1c44f31 Fix antispam plugin restoration after rspamd→SA switch`
- **Bazat pe upstream**: v74 (probabil; verificat in plan execution)
- **Remote `fork`**: `https://github.com/robertpopa22/mailinabox.git`
- **Remote `origin`**: `https://github.com/mail-in-a-box/mailinabox`

### Local fork repo (D:\github\mailinabox)
- **Branch**: `feature/rspamd-spam-filter`
- **HEAD**: `3d9eddf rspamd: brand impersonation framework`
- **Commits ahead of server**: 4
  - `3d9eddf` rspamd: brand impersonation framework
  - `dffe3c0` rspamd: fix neural + IMAPSieve Junk + courier/RO phishing rules
  - `5ebdd37` Add: CLAUDE.md project instructions
  - `30d8eb3` docs: add Geseidl Edition branding with logo and makeitcount signature

### Upstream state
- **Latest stable**: **v75** (April 20, 2026)
- **Tags disponibile**: v75 (latest), v74 (server base), v73, v72…
- **Changelog v74→v75**: roundcube 1.6.15, accessibility fixes, S3 backup fix, fail2ban Nextcloud filter, name resolution fix

### Customizari critice (must preserve)
| Categorie | Locatie | Continut |
|---|---|---|
| **Postfix** | `/etc/postfix/main.cf` + `master.cf` | TBD inventariat |
| **Dovecot** | `/etc/dovecot/conf.d/99-local*.conf`, `90-imapsieve.conf` | imapsieve Trash → Bayes retrain, custom auth |
| **Rspamd** | `/etc/rspamd/local.d/`, `/etc/rspamd/override.d/` | force_actions DMARC reject pt Gmail forwards, brand impersonation framework, RO phishing rules, neural network |
| **Nginx** | `/etc/nginx/conf.d/local.conf` (pt MTA-STS, custom security headers) | TBD |
| **Cron jobs** | `/etc/cron.d/`: `mailinabox-nightly`, `mailinabox-nextcloud`; root crontab: `naiad_dns_monitor.py` (every 30min), `rspamd_learn_report.py` (07:00), `spam-diagnostic/monitor.sh` (hourly) | Custom monitoring |
| **Custom scripts** | `/usr/local/bin/`: `naiad_dns_monitor.py`, `rspamd_learn_report.py`, `jp.py` | Geseidl-specific monitoring |
| **Spam diagnostic** | `/root/spam-diagnostic/` | monitor.sh + monitor.log |
| **DKIM keys** | `/home/user-data/mail/dkim/` | Critical — pierdere = email signed differently |
| **TLS certs** | `/etc/letsencrypt/`, `/home/user-data/ssl/` | Cert per domeniu |
| **Mail data** | `/home/user-data/mail/mailboxes/` | 424GB total |
| **Bayes DB** | `/var/lib/redis/` (rspamd state) sau `/home/user-data/mail/spamassassin/` | ~328 spam mostre retrain in aprilie |
| **MiaB conf** | `/etc/mailinabox.conf` | STORAGE_USER, PRIMARY_HOSTNAME, PUBLIC_IP, MTA_STS_MODE |
| **Forward rules** | MiaB admin DB | biamco/energycycling/conta-ploiesti.ro → office@geseidl.ro |
| **Useri MiaB** | `/home/user-data/mail/users.sqlite` | 70+ conturi |

### Domenii hostate
- geseidl.ro (primary, ~70 useri)
- energycycling.ro (forward only)
- biamco.ro (forward only)
- conta-ploiesti.ro (forward only)

---

## 3. Target State

- **OS**: Ubuntu 24.04.x LTS (noble)
- **Kernel**: 6.8.0-x (latest noble HWE)
- **PHP**: 8.3.x (noble default)
- **MiaB**: rebased pe v75, cu custom rspamd integration + Geseidl branding pastrat
- **Email functional**: SMTP/IMAP/Webmail fara intrerupere semnificativa
- **Forwards functional**: 3 domenii continua sa redirectioneze
- **Spam filter functional**: rspamd cu Bayes DB + force_actions DMARC + brand impersonation rules

---

## 4. Risk Assessment

| Risc | Probabilitate | Impact | Mitigare |
|---|---|---|---|
| **rebase conflict major** intre fork rspamd commits si v75 | **Medie** | Mare | Rebase local intai, test compile-time, verificare config files |
| **PHP 8.0 → 8.3** breaks Nextcloud/Roundcube | Mica (v75 testeaza pe noble) | Mare | v75 release notes confirma noble support |
| **do-release-upgrade fail mid-way** (held packages, conflicts) | Mica | **Critic** | Checkpoint Hyper-V + Veeam restore = rollback in 15 min |
| **Rspamd custom rules schema break** la upgrade | Medie | Mare | Backup `/etc/rspamd/local.d/` + `override.d/` separat; revert manual |
| **Bayes DB pierdut/corrupt** | Mica | Mediu (3 luni retrain reset) | Backup explicit `/var/lib/redis/` |
| **DKIM keys pierdute** → email signed cu key nou → Gmail/Yahoo treaze ca spoofing | **Foarte mica** | **Critic** | `/home/user-data/mail/dkim/` in /home/user-data care e pe partitia /home (separata? no, same /) — backup explicit |
| **Cert Let's Encrypt revoke/expire** in timpul upgrade | Mica | Mediu | Cert curent valid >30z; backup `/etc/letsencrypt/` |
| **DNS records out-of-sync** (CF + AD) | Foarte mica | Mediu | NU schimbam DNS in upgrade |
| **Mail bounce** in timpul downtime (>30 min) | Medie | Mic-Mediu | SMTP retry 30+ min standard; downtime <2h = niciun mail pierdut definitiv |
| **MiaB v75 incompat cu fork rspamd branch** | Medie | Mare | Decision gate dupa rebase: daca conflict masiv, abandoneaza v75 → ramane v74 fork |
| **2h timeout depasit** | Medie | Mediu (rollback) | Checkpoint instant rollback la t=2h daca nu functional |
| **Hyper-V Replica conflict** | Foarte mica (MAIL02 nu in replica list per CLAUDE.md) | Mic | Verifica `Get-VMReplication -VMName GES-MAIL02` inainte |

---

## 5. Pre-requisites Checklist

**Inainte de fereastra mentenanta:**
- [ ] Confirmare user GO
- [ ] Test rebase local fara push (verifica conflicte v74→v75 + rspamd commits)
- [ ] Daca rebase local OK, push branch nou `geseidl-edition-v75` pe fork
- [ ] Disk space pe S00: verifica >50GB free pentru checkpoint VM 800GB
- [ ] Ultim Veeam B&R backup MAIL02 vechime cunoscuta (+ trigger ad-hoc inainte de upgrade)
- [ ] Window mentenanta: noaptea (02:00-05:00 EEST) sau weekend
- [ ] Notificare useri (sau skip — internal tool, low impact off-hours)
- [ ] Actualizat CLAUDE.md si MAIL02.log.md cu plan
- [ ] Pregatit runbook rollback scris (printat / accesibil offline)

---

## 6. Step-by-Step Procedure

### Faza 0 — Pregatire (1h, NU downtime)

1. **Rebase local pe v75** (in `D:\github\mailinabox`)
   ```bash
   git fetch upstream
   git checkout -b geseidl-edition-v75 feature/rspamd-spam-filter
   git rebase v75
   # rezolva conflicte (probabil rspamd integration vs v75 changes)
   # commit rezolvarile
   ```
   **Decision gate**: daca >10 conflicte non-trivial, **STOP**. Plan B: ramai pe fork v74, doar OS upgrade.

2. **Verifica fisierele MiaB modificate** post-rebase:
   ```bash
   git diff v75..geseidl-edition-v75 -- setup/ management/ conf/
   ```
   Asigura ca rspamd integration + Geseidl branding intacte.

3. **Push fork branch nou** `geseidl-edition-v75`:
   ```bash
   git push origin geseidl-edition-v75
   ```

4. ~~Veeam B&R live backup~~ — **MUTAT in Faza 2 post-shutdown** (user instructiune 2026-04-30: backup doar dupa shutdown pentru consistent state, nu pe VM running)

5. **Backup local fisiere critice de pe MAIL02** (rsync / scp):
   - `/etc/postfix/`
   - `/etc/dovecot/conf.d/`
   - `/etc/rspamd/local.d/`, `/etc/rspamd/override.d/`
   - `/etc/nginx/conf.d/`, `/etc/nginx/sites-*/`
   - `/etc/cron.d/mailinabox-*`, root crontab
   - `/usr/local/bin/*.py`, `/root/spam-diagnostic/`
   - `/etc/letsencrypt/`
   - `/etc/mailinabox.conf`
   - `/var/lib/redis/dump.rdb` (Bayes state)
   - **NU /home/user-data** (424GB, ramane in checkpoint VM)

   Local: `D:\github\mailinabox\backup\mail02-pre-v75-2026-XX-XX\`

6. **Commit backup tarball** pe fork:
   ```bash
   cd D:/github/mailinabox
   git checkout -b backup/mail02-pre-upgrade-2026-XX-XX
   tar czf backup/mail02-configs.tar.gz backup/mail02-pre-v75-2026-XX-XX/
   git add backup/
   git commit -m "[backup] MAIL02 configs pre-upgrade v75"
   ```

### Faza 1 — Pre-shutdown (15 min)

7. **Final rsync** /home/user-data/mail/dkim/ + DB users + sieve scripts to local backup
8. **Stop apt-daily.timer** sa nu interferi
9. **Notifica DIT/admin** prin Telegram bot

### Faza 2 — Snapshot (10-20 min)

10. **Graceful shutdown VM**:
    ```bash
    ssh ges-mail02 'sudo shutdown -h +1 "scheduled upgrade Ubuntu 22.04→24.04"'
    ```
    Astept ~2 min pana VM stops.

11. **Hyper-V Checkpoint** (din GES051WS):
    ```powershell
    Invoke-Command -ComputerName GES-S00 -ScriptBlock {
        Checkpoint-VM -Name "GES-MAIL02" -SnapshotName "pre-2404-v75-upgrade-2026-04-30-XXXX"
    }
    ```

12. **Veeam B&R ad-hoc full backup** (UNICUL, post-shutdown = consistent state):
    PS Direct via S00 → S01 (PS7 endpoint required pt v13 — vezi `feedback_veeam_ps7_remoting.md`).
    Trigger `Start-VBRJob` sau `Start-VBRBackupJob` pe job MAIL02.
    Astept finalizare (~30-45 min on stopped VM).
    **Decision gate G2**: daca Veeam fail → STOP, retry. Doar Hyper-V checkpoint NU e suficient (single point of failure pe S00 disk).

13. **Boot VM** pentru upgrade.

### Faza 3 — OS Upgrade (60-90 min)

14. **Pre-upgrade clean**:
    ```bash
    apt update && DEBIAN_FRONTEND=noninteractive apt upgrade -y
    apt autoremove -y
    ```

15. **do-release-upgrade**:
    ```bash
    apt install update-manager-core
    do-release-upgrade -d   # -d = dezvoltare (24.04 inca poate fi recomandat sau LTS-to-LTS direct)
    ```
    Sau:
    ```bash
    do-release-upgrade   # daca 24.04 e marked stable LTS-to-LTS
    ```
    Verifica `/etc/update-manager/release-upgrades` `Prompt=lts`.

    **Interactiv**: confirma update sources (Y), services restart auto (Y), conffile defaults (KEEP custom).
    Cu DEBIAN_FRONTEND=noninteractive nu va prompt.

16. **Reboot post-upgrade**.

17. **Verifica boot**:
    ```bash
    uname -r   # 6.8.x?
    lsb_release -a   # Ubuntu 24.04 noble?
    systemctl is-system-running   # 'running' sau 'degraded'?
    ```

### Faza 4 — MiaB Upgrade v74 fork → v75 rebased (30-60 min)

18. **Pull fork branch nou**:
    ```bash
    cd /root/mailinabox
    git fetch fork
    git checkout geseidl-edition-v75
    git reset --hard fork/geseidl-edition-v75
    ```

19. **Re-run MiaB setup** (idempotent):
    ```bash
    cd /root/mailinabox
    sudo ./setup/start.sh
    ```
    Va detecta Ubuntu 24.04 noble + reinstall toate (postfix 3.8, dovecot 2.3.x or newer, rspamd, php8.3, nginx).

20. **Verifica config restore**:
    - rspamd: `/etc/rspamd/local.d/*` + `override.d/*` — manual restore daca setup le-a sters/overwritat
    - Custom dovecot 99-local* — manual restore din backup
    - cron jobs custom — verifica ca raman

21. **Restart services**:
    ```bash
    systemctl restart postfix dovecot rspamd nginx php8.3-fpm
    ```

### Faza 5 — Verify (15-30 min)

22. **Local tests**:
    - `nc -zv localhost 25 587 993 465` — porturi listening
    - `swaks --to robert.popa@geseidl.ro --from test@geseidl.ro --server localhost` — SMTP local
    - IMAP login test (curl sau swaks IMAP)
    - Admin panel: `https://mail.geseidl.ro/admin` — login + verifica useri/forwards

23. **External tests**:
    - Send email din alta locatie → mailbox geseidl
    - Reply din mailbox → external (verifica DKIM signing)
    - Verifica Gmail forward: trimite la `office@biamco.ro` → ajunge la `office@geseidl.ro`?
    - Test Outlook/Thunderbird configurare cu un cont real

24. **Spam filter**:
    - Trimite spam test (gtube string) → marcheaza spam?
    - Verifica rspamd Web UI `http://10.0.1.89:11334`
    - Verifica Bayes DB intact: `redis-cli -n 0 keys 'rs_*' | head -5`

25. **DNS / DKIM**:
    - `dig TXT mail._domainkey.geseidl.ro` — DKIM record matches `/home/user-data/mail/dkim/mail/private.txt`?
    - `dig MX geseidl.ro` — pointeaza mail.geseidl.ro
    - `nslookup -type=TXT _dmarc.geseidl.ro` — DMARC record OK

26. **Cron / monitoring**:
    - Verifica `systemctl list-timers`
    - `cat /var/log/rspamd_learn_report.log` ultimul rulare OK
    - `cat /var/log/naiad_dns_monitor.log` ultimul rulare OK

### Faza 6 — Cleanup post-success (10 min)

27. **Sterge checkpoint Hyper-V** (per regula NET-ADMIN #12):
    ```powershell
    Invoke-Command -ComputerName GES-S00 -ScriptBlock {
        Remove-VMSnapshot -VMName GES-MAIL02 -Name "pre-2404-v75-upgrade-2026-04-30-XXXX"
    }
    ```

28. **Update logs + commit pe NET-ADMIN**:
    - GESEIDL/GES-MAIL01/GES-MAIL02.log.md cu detalii upgrade
    - GESEIDL/GES-MAIL01/SECURITY.md cu noua versiune

29. **Update fork mailinabox**:
    - Branch `geseidl-edition-v75` → merge in `feature/rspamd-spam-filter` (sau redenumeste branch)
    - Push tag `geseidl-v75-deployed-2026-XX-XX`
    - Update CLAUDE.md fork cu detalii rebase

---

## 7. Rollback Runbook (DACA ESUEAZA SAU >2h)

### Trigger rollback daca:
- do-release-upgrade lasa sistem nebootabil
- MiaB setup/start.sh esueaza repetat post-upgrade
- Mail flow nu functioneaza dupa 30 min troubleshooting
- t > 2h fara mail functional

### Procedura (15 min):

1. **Force shutdown VM**:
    ```powershell
    Invoke-Command -ComputerName GES-S00 -ScriptBlock { Stop-VM -Name GES-MAIL02 -TurnOff }
    ```

2. **Restore checkpoint Hyper-V**:
    ```powershell
    Invoke-Command -ComputerName GES-S00 -ScriptBlock {
        Restore-VMSnapshot -VMName GES-MAIL02 -Name "pre-2404-v75-upgrade-2026-04-30-XXXX" -Confirm:$false
    }
    ```

3. **Boot VM**:
    ```powershell
    Invoke-Command -ComputerName GES-S00 -ScriptBlock { Start-VM -Name GES-MAIL02 }
    ```

4. **Verifica**:
    - SSH conectivity
    - SMTP/IMAP listening
    - Test send/receive
    - Admin panel accesibil

5. **Daca checkpoint corupt**: Veeam Restore VM (~45 min RTO)

6. **Documenteaza esec**:
    - Adauga la `D:\github\mailinabox\UPGRADE_PLAN_2026-04-30.md` sectiunea "Rollback log"
    - Note exact unde a esuat (faza, comanda, mesaj eroare)
    - Commit + push fork

---

## 8. Time Estimates

| Faza | Durata | Cumulat |
|---|---|---|
| 0. Pregatire (rebase + backup) | 60 min | 60 min |
| 1. Pre-shutdown | 15 min | 75 min |
| 2. Snapshot (shutdown + checkpoint + Veeam) | 25 min | 1h40 |
| 3. OS upgrade do-release-upgrade | 75 min | 2h55 |
| 4. MiaB rebase deploy + setup/start.sh | 45 min | 3h40 |
| 5. Verify | 25 min | 4h05 |
| 6. Cleanup | 10 min | 4h15 |

**Total**: ~4h. Maintenance window real (downtime mail): **~2h** (Faze 2-5).

**Timebox user**: 2h. Daca dupa 2h de la shutdown nu e mail functional → rollback.

---

## 9. Decision Gates

| Gate | Cand | Daca FAIL → |
|---|---|---|
| **G1**: Rebase v74-fork → v75 reuseste local | Faza 0 step 1 | Plan B: doar OS upgrade, ramai pe v74 fork |
| **G2**: Veeam backup pre-upgrade succeeds | Faza 0 step 4 | STOP. Investigheaza Veeam, retry |
| **G3**: VM boots dupa do-release-upgrade | Faza 3 step 17 | Rollback imediat |
| **G4**: setup/start.sh succeeds pe noble | Faza 4 step 19 | Investigeaza 30 min, apoi rollback |
| **G5**: Mail flow functional in 30 min | Faza 5 | Investigeaza 30 min, apoi rollback |
| **G6**: t < 2h de la shutdown | Continuu | Rollback la t=2h indiferent de stare |

---

## 10. Notes

- **Acest fisier ramane in repo** indiferent de rezultat. Daca esueaza, adauga sectiune "Rollback log" cu detalii.
- **Comituri pe fork mailinabox**: branch `geseidl-edition-v75` pentru rebased version, branch `backup/mail02-pre-upgrade-XXXX` pentru configs.
- **NU este replica MAIL02 pe Hyper-V** (per CLAUDE.md tabel — replica activa: FILE01 S00→S12, RDS01+SQL01 S00→S10). MAIL02 nu in replica → checkpoint Hyper-V e singura backup VM-level.
- **Veeam B&R** = singurul backup independent de Hyper-V. Trebuie pre-upgrade fresh full.
- **Postcondition**: dupa success, pierdem ~2h mail. Pentru SMTP retry standard >24h, **niciun mail definitiv pierdut**.

---

## 11. Rebase Test Result (2026-04-30 13:35)

Test rebase local executat (branch `geseidl-edition-v75-test`, dropped post-test):

```
git checkout -b geseidl-edition-v75-test feature/rspamd-spam-filter
git rebase v75
# Rebasing (1/8) ... (8/8) Successfully rebased
```

**Rezultat**: ✅ **8/8 commits aplicate cu 0 conflicte**

**Files modified vs v75** (875 ins, 10 del):
- `setup/rspamd.sh` (NEW, +446 lines) — rspamd integration custom
- `management/daemon.py` (+96) — rspamd admin endpoints
- `management/templates/system-spam.html` (NEW, +133) — UI rspamd
- `setup/spamassassin.sh` (+72) — SA reverse migration
- `setup/mail-postfix.sh` (+24) — rspamd milter integration
- `management/status_checks.py` (+26)
- `management/templates/index.html` (+5)
- `conf/nginx-primaryonly.conf` (+1)
- `CLAUDE.md` (NEW, +62)
- `README.md` (+20) — Geseidl Edition branding

**Conclusion Gate G1**: PASS. Riscul rebase major eliminat. Plan procedeaza cu MiaB v75 path (NU plan B v74-only).

---

## Status (live)

- [x] **Faza 0** complet: rebase fork @ `geseidl-edition-v75` (9/9 commits 0 conflicts) + configs backup tarball 39M (185 files) → branch `backup/mail02-pre-upgrade-2026-04-30`
- [x] **Faza 1** complet: mail queue empty, apt-daily.timer disabled
- [x] **Faza 2** in progress:
  - shutdown VM 14:06 EEST ✅
  - Hyper-V checkpoint `pre-2404-v75-upgrade-2026-04-30-1406` ✅
  - VM booted (Veeam auto-boot) ✅
  - Veeam B&R full backup running PARALEL pe checkpoint snapshot (PS7 7.4.13 installat pe S01, endpoint registered)
- [x] **Faza 3** in progress (PARALEL cu Veeam):
  - 14:39 EEST: `mail02_release_upgrade.sh` background pe MAIL02
  - apt upgrade pre-clean DONE
  - update-manager-core installing
  - do-release-upgrade jammy→noble in progress
- [ ] **Faza 4**: deploy fork v75 + setup/start.sh
- [ ] **Faza 5**: verify SMTP/IMAP/forwards/DKIM/spam
- [ ] Cleanup
- [ ] Plan reviewed by user
- [ ] Pre-requisites complete
- [ ] Maintenance window scheduled: TBD
- [ ] Faza 0 done
- [ ] Faza 1-2 done
- [ ] Faza 3 done
- [ ] Faza 4 done
- [ ] Faza 5 verified
- [ ] Faza 6 cleanup
- [ ] Final commit + log
