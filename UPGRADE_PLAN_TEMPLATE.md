# Upgrade Plan Template — Mail-in-a-Box 22.04 → 24.04

> **How to use this template**: copy this file to your own private notes/repo and fill in the bracketed `[...]` placeholders for your environment. Treat it as a runbook checklist. Do not commit your filled-in version to a public repo (it will reveal your hostname, public IP, domains, and similar identifiers).
>
> Companion documents in this repo:
> - **Detailed step-by-step**: [`UPGRADE_22.04_TO_24.04_GUIDE.md`](UPGRADE_22.04_TO_24.04_GUIDE.md)
> - **Backup script**: [`setup-helpers/backup-mail-configs.sh`](setup-helpers/backup-mail-configs.sh)
> - **Phased automation**: [`setup-helpers/upgrade-2204-to-2404.sh`](setup-helpers/upgrade-2204-to-2404.sh)

---

## 1. Scope

- **Server**: `[your-mail-vm-name]` (`[private-IP]`, public `[public-IP]`)
- **Hypervisor host**: `[hyperv-host / esxi-host / cloud-provider]`
- **Maintenance window**: `[date + start time + duration]` (target: 2-3h, real downtime ~1-1.5h)
- **Status**: EXPERIMENTAL — if it fails, rollback to checkpoint, document outcome

Out of scope (do **not** change during the upgrade):
- Hostname (e.g. `mail.example.com` stays)
- Public/private IPs
- DNS records (Cloudflare / external DNS unchanged)
- VLAN / network config

---

## 2. Pre-upgrade inventory (fill in)

### OS / kernel / packages
- Current OS: `[Ubuntu 22.04.x]`
- Current kernel: `[5.15.0-x-generic]`
- Free disk on `/`: `[XX GB]` (need 5+ GB)
- RAM: `[X GB]`
- `/home/user-data` size: `[XXX GB]`

### Software stack on the server (from `apt list --installed`)
- PHP: `[8.0.x from Sury repo]`
- Postfix: `[3.6.x]`
- Dovecot: `[2.3.x]`
- rspamd: `[2.7]` (if used)
- nginx, redis-server, fail2ban — present + versions

### MiaB version
- Local repo path: `[/root/mailinabox]`
- Branch: `[main / feature/rspamd-spam-filter / etc.]`
- HEAD commit: `[hash]`
- Based on upstream tag: `[v74 / v75]`

### Hosted domains
- Number: `[N]`
- Roles: primary + alias-only / forward-only / Nextcloud-active / etc. (no need to list FQDNs in your saved plan)

### Active users
- Approximate count: `[N]`
- Notification plan: `[email broadcast / Slack / skip if internal-only]`

### Custom configs to preserve
- Postfix custom: `[main.cf overrides? milters? virtual maps?]`
- Dovecot custom: `[99-local-*.conf / sieve scripts / IMAPSieve]`
- rspamd custom: `[local.d/* / override.d/* / forbidden_file_extensions]`
- nginx custom: `[conf.d/local.conf / sites-available/*]`
- Cron jobs: `[mailinabox-* / custom monitoring scripts]`
- Custom scripts: `[/usr/local/bin/*.py]`
- Bayes DB: `/var/lib/redis/dump.rdb`
- DKIM keys: `/home/user-data/mail/dkim/`
- TLS certs: `/etc/letsencrypt/`, `/home/user-data/ssl/`
- MiaB conf: `/etc/mailinabox.conf`
- User DB: `/home/user-data/mail/users.sqlite`
- Forwards: `/home/user-data/mail/aliases`

---

## 3. Target state

- OS: Ubuntu 24.04.x LTS (noble)
- Kernel: 6.8.x
- PHP: 8.3.x (or kept on 8.0 from Sury — see GUIDE Step 3)
- MiaB: rebased on latest upstream tag with your customs preserved
- Mail service: functional with no message loss
- Forwards: continue to work
- Spam filter (rspamd or SpamAssassin): functional with retained Bayes state

---

## 4. Risk register (mark relevant ones)

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| Major rebase conflict against upstream | Low-Med | High | Test rebase locally first; have a Plan B (skip new tag, stay on current) |
| do-release-upgrade fails midway | Low | **Critical** | VM-level checkpoint + Veeam/equivalent. Rollback ~15 min. |
| Custom rspamd schema breaks | Med | Med-High | Backup `/etc/rspamd/local.d/*` + `override.d/*`; manual restore |
| Bayes DB lost/corrupt | Low | Med (months of training reset) | Explicit backup `/var/lib/redis/dump.rdb` |
| **DKIM keys lost** | Very low | **Critical** | Tarball backup of `/home/user-data/mail/dkim/`; verify post-upgrade with `dig TXT mail._domainkey.[domain]` |
| TLS cert revoke/expire during window | Very low | Med | Cert valid >30d; backup `/etc/letsencrypt/`; do not change DNS |
| Mail bounce during downtime >2h | Low (if window <2h) | Low-Med | Standard SMTP retry 30+ min, no permanent loss <24h |
| MiaB upstream version incompatible with custom branch | Low-Med | High | Test rebase Gate G1 before window |
| Window timeout | Med | Med (rollback) | Hard timebox at 2h post-shutdown |

---

## 5. Pre-requisites checklist

Before the maintenance window:
- [ ] Stakeholder approval (if applicable)
- [ ] Test rebase locally (Gate G1) — push fork branch only if conflict-free
- [ ] Verify hypervisor host has free disk (50+ GB recommended for VM checkpoint)
- [ ] Verify VM-level backup is recent (Veeam / equivalent <24h)
- [ ] Confirm console access works (vmconnect, IPMI, KVM, virsh console, etc.)
- [ ] Whitelist your admin IPs in **fail2ban** AND **UFW** (most often forgotten — see GUIDE 0.3)
- [ ] Notify users (skip if internal-only and downtime <2h)
- [ ] Print or have offline access to: this plan, GUIDE, rollback runbook
- [ ] Disk space on server: 5+ GB free on `/`
- [ ] Mail queue empty: `mailq | tail -1`

---

## 6. Phase plan (timing estimates)

| Phase | Duration | Downtime? | Action |
|---|---|---|---|
| 0 — Prep (rebase + tarball backup of configs) | 1h | No | `setup-helpers/backup-mail-configs.sh`, push fork branch |
| 1 — Pre-shutdown | 15 min | No | Stop apt-daily timer, mail queue empty, final notif |
| 2 — Snapshot | 25 min | **Yes (start)** | Shutdown → hypervisor checkpoint → VM-level backup (parallel on snapshot) → boot |
| 3 — do-release-upgrade | 60-90 min | **Yes** | `setup-helpers/upgrade-2204-to-2404.sh --phase os` (auto reboots) |
| 4 — MiaB rebuild | 30-60 min | **Yes** | `--phase miab` (rebuild venv + reinstall pip deps + restart mailinabox.service); manual fixes if any module missing |
| 5 — Verify | 15-30 min | End | `--phase verify` + external test from another network |
| 6 — Cleanup | 10 min | No | Re-enable apt timers; wait 24h before deleting checkpoint |

**Total wall clock**: ~4h. **Real downtime**: ~1-2h (Phase 2-5).

**Hard timebox**: 2h post-shutdown. If by t=2h mail is not functional → rollback per Phase 7.

---

## 7. Decision gates

| Gate | When | If FAIL → |
|---|---|---|
| **G1** Rebase fork on new upstream succeeds | Phase 0 | Plan B: stay on current branch; OS-only upgrade |
| **G2** VM-level backup completes | Phase 2 | STOP, retry, or escalate to fresh-install plan |
| **G3** VM boots after do-release-upgrade | Phase 3 end | Rollback to checkpoint |
| **G4** mailinabox.service starts | Phase 4 | 30 min troubleshoot, then rollback |
| **G5** Mail flow functional in 30 min | Phase 5 | Rollback |
| **G6** t < 2h since shutdown | Continuous | Rollback at t=2h regardless of state |

---

## 8. Rollback runbook

### Trigger criteria (any one):
- VM not bootable after upgrade
- mailinabox.service repeatedly fails after 30 min
- Mail flow non-functional after 30 min troubleshooting
- t > 2h since shutdown without functional mail

### Procedure (~15 min):

1. **Force shutdown VM** (if needed)
   ```powershell
   Stop-VM -Name "[vm-name]" -TurnOff
   ```

2. **Restore checkpoint**
   ```powershell
   Restore-VMSnapshot -VMName "[vm-name]" -Name "[snapshot-name]" -Confirm:$false
   ```
   (Adapt for VirtualBox / ZFS / etc.)

3. **Boot VM**
   ```powershell
   Start-VM -Name "[vm-name]"
   ```

4. **Verify**
   - SSH connectivity restored
   - SMTP/IMAP listening
   - Send/receive test mail
   - Admin panel accessible

5. **If checkpoint corrupt**: restore from VM-level backup (Veeam etc.) → ~30-60 min RTO.

6. **Document the failure**: which phase, which command, exact error message. Open an issue against the fork. Helps everyone.

---

## 9. Post-upgrade verification checklist

- [ ] `cat /etc/os-release` → 24.04.x noble
- [ ] `uname -r` → 6.8.0-x
- [ ] `systemctl is-active postfix dovecot rspamd nginx redis-server fail2ban opendmarc opendkim mailinabox` → all active
- [ ] `ss -tln | grep -E ':(25|465|587|993|443|80|11332|11334|10222) '` → all listening
- [ ] `mailq | tail -1` → "Mail queue is empty"
- [ ] Send test mail loopback → delivered to mailbox
- [ ] Send test mail from external account → delivered with DKIM signed
- [ ] Send test reply external → DKIM verified by recipient
- [ ] IMAP login works (test from real client)
- [ ] Webmail (Roundcube) works
- [ ] Admin panel HTTPS 200 OK
- [ ] DKIM TXT record matches: `dig TXT mail._domainkey.[your-domain]` against `/home/user-data/mail/dkim/mail/private.txt`
- [ ] Forwards (if any) deliver as expected
- [ ] Spam filter classifies test message correctly
- [ ] No failed systemd units: `systemctl --failed`

---

## 10. Cleanup (after 24h soak)

- [ ] Mail traffic looks normal in `/var/log/mail.log`
- [ ] No new failed services
- [ ] Delete hypervisor checkpoint
- [ ] Re-enable `apt-daily.timer` and `apt-daily-upgrade.timer`
- [ ] Optional: schedule a daily reboot timer to pick up future kernel updates
- [ ] Document outcome (success or failure) — open an issue here so others can learn

---

## 11. Status (track as you go)

- [ ] Plan reviewed and adapted to my environment
- [ ] G1 — rebase test: PASS / FAIL
- [ ] Phase 0 — Prep done
- [ ] Phase 1 — Pre-shutdown done
- [ ] Phase 2 — Snapshot + VM backup done
- [ ] Phase 3 — do-release-upgrade complete
- [ ] Phase 4 — MiaB venv rebuilt + service running
- [ ] Phase 5 — All verifications pass
- [ ] Phase 6 — Cleanup (24h soak + checkpoint deletion)
- [ ] Outcome documented (issue / blog / fork PR)

---

## Appendix: my actual reference deployment

For comparison, the Geseidl reference deployment that this template was distilled from:
- ~70 active mailboxes
- ~400 GB user-data
- Multiple hosted domains (one primary + always-BCC archive forwards)
- Hyper-V hypervisor on Windows Server, Veeam B&R for VM-level backup
- Real downtime: 1h12min, sub 2h timebox
- Outcome: success — all mail flows verified post-upgrade
- Tag of the validated state: `geseidl-v75-2204to2404-validated`

Your numbers will differ. Adapt the time estimates accordingly: more user-data → longer Veeam backup (but it can run in parallel on the checkpoint snapshot, so it does not extend downtime). More custom configs → longer Phase 4 venv rebuild iterations.
