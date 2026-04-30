# Mail-in-a-Box: In-place Ubuntu 22.04 → 24.04 Upgrade Guide

> **Status**: ✅ Successfully validated 2026-04-30 on a production server (70+ users, 400+ GB user-data, multiple hosted domains). Real downtime: **~1h12min**.
> **Official MiaB warning**: v75 officially supports ONLY Ubuntu 22.04. This guide describes how to safely bypass that limitation.
> **Audience**: intermediate-level Linux admins able to follow step-by-step commands. If this is your first Linux server, **don't try this yet** — test on a disposable VM first.

---

## Why would you do this?

- Ubuntu 22.04 LTS standard support runs until April 2027. **Not urgent**, but a newer kernel sooner is better.
- 24.04 has kernel 6.8+ vs 5.15 = newer security patches (e.g. CVE-2026-31431 "Copy Fail"), updated Hyper-V drivers, PHP 8.3 (vs 8.0), Python 3.12 (vs 3.10).
- **Mostly**: avoid a panicked last-minute upgrade when 22.04 reaches EOL.

## Why is this officially unsupported?

The MiaB team doesn't have resources to test + support 2 Ubuntu versions simultaneously. Their code has a strict check in `setup/preflight.sh`:

```bash
if [ "${OS_RELEASE_VERSION_ID:-}" != "22.04" ]; then
    echo "Mail-in-a-Box only supports being installed on Ubuntu 22.04, sorry."
    exit 1
fi
```

In reality, **most components work without modifications on 24.04** (Postfix, Dovecot, rspamd, nginx, fail2ban). Only the PHP version and the Python venv need minor changes.

---

## Prerequisites

### On the server
- [ ] Ubuntu 22.04 LTS running MiaB (officially installed)
- [ ] Free disk: minimum 5GB on `/` for packages + new initramfs
- [ ] RAM: minimum 2GB (3GB recommended) during the upgrade
- [ ] Root or sudo access
- [ ] **Console access** to the VM (KVM/Hyper-V/VirtualBox/IPMI) — **MANDATORY** in case SSH drops

### On your workstation (admin)
- [ ] VM-level backup available (Hyper-V snapshot, ZFS snapshot, Veeam, etc.)
- [ ] Access to the MiaB fork repo (or upstream MiaB if not using a fork)
- [ ] Authority to restore from backup if it fails
- [ ] 2-3 hour maintenance window (~1h actual downtime)
- [ ] **Important**: notify your users. Standard SMTP retry is 30+ min, so if downtime is <2h no mail is lost, but it's polite to give a heads-up.

---

## Important warnings

> **⚠️ If this fails and you have no VM-level backup, mailboxes may be unrecoverable. DO NOT proceed without backup.**

> **⚠️ If SSH drops mid-upgrade, you need physical/virtual console access. Ensure you can access vmconnect/IPMI/KVM BEFORE starting.**

> **⚠️ This is experimental. If you use a hypervisor other than Hyper-V, adapt the checkpoint/backup steps to your platform.**

---

## Step 0 — Preparation (1h, no downtime)

### 0.1 Local config backup (quick)

Create a tarball of all critical configs. If subsequent steps wipe something, you have a way to restore:

```bash
ssh root@mail.example.com 'bash -s' < setup-helpers/backup-mail-configs.sh
# Output: /tmp/mail-configs-YYYYMMDD-HHMM.tar.gz (~30-50MB)

# Download locally
scp root@mail.example.com:/tmp/mail-configs-*.tar.gz ./backup/
```

The backup includes: `/etc/postfix/`, `/etc/dovecot/`, `/etc/rspamd/`, `/etc/nginx/`, `/etc/letsencrypt/`, `/etc/mailinabox.conf`, `/usr/local/bin/*.py` (custom scripts), `/var/lib/redis/dump.rdb` (rspamd Bayes DB), `/home/user-data/mail/dkim/` (DKIM keys — CRITICAL), `/home/user-data/mail/users.sqlite` (user DB), `/home/user-data/mail/aliases` (forwards), `/home/user-data/conf/`, `/home/user-data/ssl/`.

> **DO NOT commit the tarball to a public git repo** — it contains private keys (dovecot TLS, DKIM, Let's Encrypt account). Keep it local or in a private repo.

### 0.2 Empty mail queue + stop auto-update timers

```bash
mailq | tail -1            # should be "Mail queue is empty" or empty
systemctl stop apt-daily.timer apt-daily-upgrade.timer
```

### 0.3 Whitelist admin IPs in fail2ban + UFW (CRITICAL)

> **If you skip this step, you'll lock yourself out after the upgrade.** fail2ban gets reinstalled with a fresh config during the upgrade — your admin IPs will NOT be in the whitelist. Rapid polling = automatic ban.

```bash
# Add your admin IPs to /etc/fail2ban/jail.local
sudo tee -a /etc/fail2ban/jail.local <<'EOF'

[sshd]
ignoreip = 127.0.0.1/8 ::1 10.0.0.0/8 192.168.0.0/16 100.64.0.0/10
EOF

# UFW: explicitly allow SSH for admin subnet (NOT LIMIT)
sudo ufw allow from 10.0.0.0/8 to any port 22 proto tcp
sudo ufw allow from 192.168.0.0/16 to any port 22 proto tcp
```

Adjust subnets to match your network. **This section is the most often forgotten and the #1 cause of wasted time.**

---

## Step 1 — Snapshot + VM-level backup (15-30 min)

### 1.1 Graceful VM shutdown

```bash
ssh root@mail.example.com 'shutdown -h now'
```

Wait until the VM is fully stopped (verify via hypervisor).

### 1.2 Hypervisor checkpoint

**Hyper-V:**
```powershell
Checkpoint-VM -Name "your-mail-vm" -SnapshotName "pre-2404-upgrade-$(Get-Date -Format yyyyMMdd-HHmm)"
```

**VirtualBox:**
```bash
VBoxManage snapshot "your-mail-vm" take "pre-2404-upgrade-$(date +%Y%m%d-%H%M)"
```

**ZFS:**
```bash
zfs snapshot rpool/vm/mail@pre-2404-upgrade-$(date +%Y%m%d-%H%M)
```

**On bare-metal without a hypervisor**: use a file-system level backup (rsnapshot, borgbackup) with the VM stopped.

### 1.3 VM-level backup (Veeam / equivalent) — CAN RUN IN PARALLEL

The VM backup reads from the checkpoint, so it can run in parallel with subsequent steps. **You don't have to wait for it to finish.**

```powershell
# Veeam B&R
Start-VBRJob -Job (Get-VBRJob -Name "MAIL02-Backup") -FullBackup
```

### 1.4 Boot the VM

```powershell
Start-VM -Name "your-mail-vm"
```

Wait 1-2 min until SSH is available again.

---

## Step 2 — Ubuntu 22.04 → 24.04 upgrade (60-90 min)

### 2.1 Pre-clean apt

```bash
DEBIAN_FRONTEND=noninteractive apt update
DEBIAN_FRONTEND=noninteractive apt upgrade -y \
    -o Dpkg::Options::="--force-confdef" \
    -o Dpkg::Options::="--force-confold"
apt autoremove -y
```

### 2.2 Configure release-upgrade

```bash
apt install -y update-manager-core
sed -i 's/^Prompt=.*/Prompt=lts/' /etc/update-manager/release-upgrades
```

### 2.3 Run release-upgrade NONINTERACTIVE

```bash
DEBIAN_FRONTEND=noninteractive do-release-upgrade \
    -f DistUpgradeViewNonInteractive \
    -m server \
    --allow-third-party
```

> **Duration**: 60-90 min depending on disk I/O and package count. Output is verbose. You'll see hundreds of "Setting up package..." lines. Normal.

> **If it fails midway**: don't panic. Restore from the checkpoint (Step 6) and retry.

### 2.4 Reboot

```bash
shutdown -r +1 "release-upgrade complete"
```

The VM reboots into **kernel 6.8.x** + Ubuntu 24.04 noble.

### 2.5 Verify boot

```bash
ssh root@mail.example.com
cat /etc/os-release   # PRETTY_NAME="Ubuntu 24.04.x LTS"
uname -r              # 6.8.0-x-generic
```

---

## Step 3 — Re-deploy MiaB management daemon (15-30 min)

> **This is the main difference vs the official upgrade.** Components based on Ubuntu packages (postfix, dovecot, rspamd, nginx) were upgraded automatically. The Python component (management daemon) runs in a dedicated venv configured for Python 3.10 (jammy). We now have Python 3.12 (noble) → the old venv no longer works.

### 3.1 Diagnose management daemon

```bash
systemctl status mailinabox.service
# Expected: failed with "ModuleNotFoundError: No module named 'gunicorn'"
```

### 3.2 Rebuild venv

```bash
apt install -y python3-venv python3-dev libssl-dev libffi-dev build-essential
rm -rf /usr/local/lib/mailinabox/env
python3 -m venv /usr/local/lib/mailinabox/env
/usr/local/lib/mailinabox/env/bin/pip install --upgrade pip
```

### 3.3 Reinstall Python dependencies

MiaB doesn't keep a standard `requirements.txt` — the lists are embedded in `setup/management.sh`:

```bash
/usr/local/lib/mailinabox/env/bin/pip install \
    flask dnspython python-dateutil expiringdict gunicorn \
    "idna>=2.0.0" cryptography psutil postfix-mta-sts-resolver \
    email_validator pyOpenSSL qrcode pyotp \
    boto3 b2sdk requests
```

> **Differences vs the official script**: I dropped the `cryptography==37.0.2` pin (old, from 2022, doesn't compile on Python 3.12). Latest cryptography (47+) works without issues.

### 3.4 Restart service

```bash
systemctl daemon-reload
systemctl restart mailinabox.service
sleep 3
systemctl is-active mailinabox.service   # expected: active
ss -tlnp | grep 10222                     # gunicorn listening
```

### 3.5 If the service fails again with another dependency

```bash
journalctl -u mailinabox.service --no-pager -n 20
# Read: ModuleNotFoundError: No module named 'X'
# Then: pip install X
# Restart service
```

Continue until all dependencies are OK. Typically 2-3 iterations.

---

## Step 4 — Verify mail flow (15 min)

### 4.1 Key services

```bash
systemctl is-active postfix dovecot rspamd nginx redis-server fail2ban opendmarc opendkim
# All should be active
```

### 4.2 Listening ports

```bash
ss -tlnp | grep -E ":(25|465|587|993|443|80|11332|11334) "
# Expected: all 8 ports LISTEN on 0.0.0.0 or ::*
```

### 4.3 Test local send

```bash
echo "Subject: post-upgrade verify $(date)
To: youradmin@example.com
From: root@mail.example.com

Test mail post-upgrade." | sendmail -t -v 2>&1 | tail -10
```

### 4.4 Verify delivery

```bash
ls -lt /home/user-data/mail/mailboxes/example.com/youradmin/cur/ | head -3
# Expected: new file with recent timestamp
```

### 4.5 Test admin panel

```bash
curl -sk https://localhost/admin/ -o /dev/null -w "HTTP %{http_code}\n"
# Expected: HTTP 200
```

### 4.6 Test IMAP login from another server

```bash
# From another server on the network:
curl -sk --max-time 10 imaps://mail.example.com:993 -u "user@example.com:password"
# Expected: ok (or auth error if password wrong — but the connection worked)
```

### 4.7 Verify DKIM

```bash
ls /home/user-data/mail/dkim/mail/
# Expected: private.txt + public.txt present
# Verify DNS match:
dig TXT mail._domainkey.example.com
```

---

## Step 5 — Cleanup (10 min)

### 5.1 Delete the hypervisor checkpoint (ONLY if all tests passed)

```powershell
Remove-VMSnapshot -VMName "your-mail-vm" -Name "pre-2404-upgrade-XXXX" -Confirm:$false
```

> **Wait at least 24h after the upgrade before deleting the checkpoint** — to be sure no late issues appear.

### 5.2 Re-enable apt timers

```bash
systemctl start apt-daily.timer apt-daily-upgrade.timer
systemctl enable apt-daily.timer apt-daily-upgrade.timer
```

### 5.3 Notify users

> Your mail is operational on Ubuntu 24.04. Thanks for your patience.

---

## Step 6 — ROLLBACK (if needed)

### 6.1 Trigger rollback

When:
- VM doesn't boot after do-release-upgrade
- Mail flow doesn't work after 30 min of troubleshooting
- Lost SSH access and can't recover (even from console)

### 6.2 Procedure

**Hyper-V:**
```powershell
Stop-VM -Name "your-mail-vm" -Force
Restore-VMSnapshot -VMName "your-mail-vm" -Name "pre-2404-upgrade-XXXX" -Confirm:$false
Start-VM -Name "your-mail-vm"
```

**VirtualBox:**
```bash
VBoxManage controlvm "your-mail-vm" poweroff
VBoxManage snapshot "your-mail-vm" restore "pre-2404-upgrade-XXXX"
VBoxManage startvm "your-mail-vm"
```

**Full restore if checkpoint corrupt**: from Veeam B&R or equivalent (~30-60 min RTO).

### 6.3 Verify recovery

```bash
ssh root@mail.example.com 'cat /etc/os-release | head -3 && systemctl is-active postfix dovecot'
# Expected: Ubuntu 22.04 + active services
```

---

## Common issues and fixes

### "SSH down after upgrade"

**Cause #1**: UFW has `LIMIT` on port 22 + your rapid polling = `iptables -m recent --update` bans you.

**Fix**: from the console, `sudo ufw allow 22/tcp` (replace LIMIT with ALLOW for the admin subnet).

**Cause #2**: SSH service flap during `dpkg --configure --pending`. **Wait 1-2 min**, retry.

### "Mail queue stuck after upgrade"

```bash
mailq                   # see stuck messages
systemctl restart postfix opendkim opendmarc dovecot
postqueue -f            # force retry
```

### "Admin panel 502 Bad Gateway"

Management daemon down. See Step 3.

### "DKIM warning: key data is not secure: /home/user-data is writeable and owned by uid X"

Noble has user-data uid 1001 (vs 1000 jammy). DKIM works, but throws a warning. Optional fix:

```bash
chown -R user-data:user-data /home/user-data
chmod 700 /home/user-data/mail/dkim
```

### "PHP 8.3-fpm not found"

MiaB uses PHP 8.0 from the Sury repo. Sury also has it for noble. The service is `php8.0-fpm`, NOT `php8.3-fpm`.

### "Cannot create venv: ensurepip not available"

```bash
apt install -y python3-venv
```

### "cryptography==37.0.2 fails to build on Python 3.12"

Use the latest:
```bash
pip install cryptography  # without version pin
```

### "/tmp gone after reboot"

Noble defaults to tmpfs `/tmp`. Use `/root/` or `/var/log/` for persistent logs.

---

## Lessons learned (from the Geseidl 2026-04-30 upgrade)

1. **Veeam B&R can run in PARALLEL with the upgrade** — it reads from the checkpoint, not the live VM. No need to wait for the backup before starting.
2. **fail2ban whitelist is the #1 time-waster**. Add your ADMIN IPs before any major operation.
3. **Console access is mandatory** — SSH will drop at least once, you need a fallback plan.
4. **`/tmp` is wiped on reboot in 24.04** — keep persistent logs in `/var/log/` or `/root/`.
5. **MiaB has a strict `setup/preflight.sh`** — running `setup/start.sh` on 24.04 will abort. Don't run it. Use the manual steps from 3.1-3.5.
6. **Postfix/Dovecot/rspamd/nginx mostly survive** the upgrade unchanged — Ubuntu packages auto-upgrade.
7. **The Python venv does NOT survive** — must be rebuilt manually.
8. **Veeam v13 needs a PS7 endpoint** — if you use PowerShell for remote ops, install PS7 first.

---

## Resources

- **Tools used**: `setup-helpers/backup-mail-configs.sh`, `setup-helpers/upgrade-2204-to-2404.sh` (in this repo)
- **MiaB upstream**: https://github.com/mail-in-a-box/mailinabox
- **This fork (Geseidl Edition)**: https://github.com/robertpopa22/mailinabox
- **Tested branch**: `main` (rebased on v75 + rspamd customs)
- **Deploy tag**: `geseidl-v75-2026-04-30`

---

## Validation status

- [x] **2026-04-30**: Geseidl Consulting Group production server
  - 70+ active users
  - Multiple hosted domains (one primary + always-BCC-archive forwards)
  - 400+ GB user-data
  - Downtime: 1h12min
  - Issues encountered: UFW limit fail2ban, /tmp clear, Python venv rebuild, missing requirements.txt
  - All issues are documented here with fixes

If you try this, please report an issue on this fork with your result (success or failure). It helps the community know whether the approach is robust.

---

## Maintained by

<a href="https://geseidl.ro/servicii-it"><img src="https://geseidl.ro/assets/icons/logo-green.png" alt="Geseidl Consulting Group" height="40"></a>

This guide is maintained by [Geseidl IT Solutions](https://geseidl.ro/servicii-it), part of [Geseidl Consulting Group](https://geseidl.ro). We use MiaB internally for ~70 users. When we decided to migrate to Ubuntu 24.04 LTS for newer security patches (kernel 6.8 with CVE-2026-31431 fix), we found that the official MiaB approach (clean VM rebuild + restore /home/user-data) was too complicated for small organisations. This guide describes how we did a successful in-place upgrade, with all problems encountered + fixes.

---

<p align="center">
  <a href="https://make-it-count.ro">
    <img src="https://geseidl.ro/assets/icons/makeitcount-amprenta-gold.png" alt="makeitcount" height="60">
  </a>
  <br>
  <sub><em>We believe great tools should be shared. Every contribution counts.</em></sub>
  <br>
  <sub><a href="https://make-it-count.ro">make-it-count.ro</a></sub>
</p>
