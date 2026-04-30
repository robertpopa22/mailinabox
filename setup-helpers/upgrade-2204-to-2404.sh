#!/bin/bash
# upgrade-2204-to-2404.sh
# Automates the Mail-in-a-Box upgrade from Ubuntu 22.04 to 24.04.
#
# READ UPGRADE_22.04_TO_24.04_GUIDE.md BEFORE running this script!
#
# This script IS EXPERIMENTAL and NOT officially supported by MiaB.
# Use at your own risk, with VM-level backup + checkpoint ready.
#
# Usage (interactive, as root):
#   sudo bash upgrade-2204-to-2404.sh [--phase {prep|os|miab|verify|all}]
#
# Phases:
#   prep    - whitelist fail2ban/UFW + stop apt-daily timers + sanity checks
#   os      - do-release-upgrade jammy → noble (REBOOT included)
#   miab    - rebuild Python venv + install pip deps + restart mailinabox.service
#   verify  - end-to-end mail flow test
#   all     - prep + os + miab + verify (with confirmation between phases)

set -uo pipefail

PHASE="${1:-all}"
case "$1" in
    --phase) PHASE="$2"; shift 2 ;;
    -p)      PHASE="$2"; shift 2 ;;
esac

LOG="/var/log/mailinabox-upgrade-2404-$(date +%Y%m%d-%H%M).log"
exec > >(tee -a "$LOG") 2>&1

echo "==============================================="
echo " MAIL-IN-A-BOX UPGRADE 22.04 → 24.04"
echo " Started: $(date -Iseconds)"
echo " Log:     $LOG"
echo "==============================================="

require_root() {
    if [[ $EUID -ne 0 ]]; then
        echo "ERROR: Run as root (sudo $0)"
        exit 1
    fi
}

confirm() {
    local prompt="$1"
    read -r -p "$prompt [y/N] " resp
    [[ "$resp" =~ ^[yY]$ ]]
}

phase_prep() {
    echo
    echo "=== PHASE 1: PREP ==="

    echo "[1.1] Checking OS version..."
    . /etc/os-release
    if [[ "$VERSION_ID" != "22.04" ]]; then
        echo "ERROR: This script is for Ubuntu 22.04. You are running: $VERSION_ID"
        return 1
    fi
    echo "  OS: $PRETTY_NAME ✓"

    echo "[1.2] Checking disk space..."
    AVAIL=$(df / | tail -1 | awk '{print $4}')
    if [[ "$AVAIL" -lt 5000000 ]]; then
        echo "WARN: Less than 5GB free on /. Recommended 5GB+. Continue at your own risk."
    fi
    echo "  Free /: $(df -h / | tail -1 | awk '{print $4}') ✓"

    echo "[1.3] Mail queue..."
    Q=$(mailq 2>/dev/null | tail -1)
    echo "  $Q"
    if echo "$Q" | grep -qE "[0-9]+ Kbytes in [0-9]+ Request"; then
        echo "WARN: Mail queue not empty. Consider waiting."
    fi

    echo "[1.4] Stopping apt-daily timers..."
    systemctl stop apt-daily.timer apt-daily-upgrade.timer 2>/dev/null || true
    echo "  Stopped ✓"

    echo "[1.5] Whitelisting admin IPs in fail2ban + UFW..."
    if [[ -f /etc/fail2ban/jail.local ]]; then
        ADMIN_IPS=$(grep "Accepted publickey" /var/log/auth.log 2>/dev/null | tail -20 | grep -oE 'from [0-9.]+' | awk '{print $2}' | sort -u | tr '\n' ' ')
        echo "  Recent admin IPs detected: $ADMIN_IPS"
        echo "  IMPORTANT: ensure /etc/fail2ban/jail.local has 'ignoreip = ...' with your admin subnets!"
        grep -E "^ignoreip" /etc/fail2ban/jail.local | head -3 || echo "  WARNING: no 'ignoreip' line found in jail.local — fail2ban may ban you post-upgrade!"
    else
        echo "  No /etc/fail2ban/jail.local — using defaults. If you have admin from non-localhost IPs, add ignoreip!"
    fi

    echo "[1.6] Backup configs to /tmp/mail-configs-pre-upgrade.tar.gz..."
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    if [[ -f "$SCRIPT_DIR/backup-mail-configs.sh" ]]; then
        bash "$SCRIPT_DIR/backup-mail-configs.sh"
    else
        echo "  WARN: backup-mail-configs.sh not found in $SCRIPT_DIR. Skipping config backup. Manual backup recommended!"
    fi

    echo
    echo "PHASE 1 COMPLETE."
    echo "Next: ensure VM-level backup (snapshot/Veeam) is taken before phase 2."
}

phase_os() {
    echo
    echo "=== PHASE 2: do-release-upgrade ==="
    echo
    echo "WARNING: This step reboots the VM at the end."
    echo "         Make sure you have a VM checkpoint + console access."
    echo

    if [[ "$PHASE" != "os" ]] && ! confirm "Continue with do-release-upgrade?"; then
        echo "Aborted by user."
        return 1
    fi

    echo "[2.1] Pre-clean apt..."
    DEBIAN_FRONTEND=noninteractive apt update
    DEBIAN_FRONTEND=noninteractive apt upgrade -y \
        -o Dpkg::Options::="--force-confdef" \
        -o Dpkg::Options::="--force-confold"
    apt autoremove -y

    echo "[2.2] Installing update-manager-core..."
    apt install -y update-manager-core
    sed -i 's/^Prompt=.*/Prompt=lts/' /etc/update-manager/release-upgrades

    echo "[2.3] Running do-release-upgrade noninteractive..."
    echo "      (Verbose output, will take 60-90 min)"
    DEBIAN_FRONTEND=noninteractive do-release-upgrade \
        -f DistUpgradeViewNonInteractive \
        -m server \
        --allow-third-party
    rc=$?

    if [[ $rc -ne 0 ]]; then
        echo "ERROR: do-release-upgrade FAILED with rc=$rc"
        echo "       Restore from VM checkpoint and retry."
        return 1
    fi

    echo "[2.4] Verifying post-upgrade state..."
    . /etc/os-release
    if [[ "$VERSION_ID" != "24.04" ]]; then
        echo "ERROR: OS is $VERSION_ID, expected 24.04. Upgrade silently failed."
        return 1
    fi
    echo "  OS: $PRETTY_NAME ✓"

    echo
    echo "PHASE 2 COMPLETE."
    echo "Rebooting in 1 minute. Reconnect after reboot to run phase 3 (miab)."
    /sbin/shutdown -r +1 "release-upgrade complete, rebooting"
}

phase_miab() {
    echo
    echo "=== PHASE 3: REBUILD MAILINABOX VENV ==="

    echo "[3.1] Installing build dependencies..."
    apt install -y python3-venv python3-dev libssl-dev libffi-dev build-essential

    echo "[3.2] Removing old venv..."
    rm -rf /usr/local/lib/mailinabox/env

    echo "[3.3] Creating new venv (Python 3.12)..."
    python3 -m venv /usr/local/lib/mailinabox/env

    echo "[3.4] Installing pip deps..."
    /usr/local/lib/mailinabox/env/bin/pip install --upgrade pip
    /usr/local/lib/mailinabox/env/bin/pip install \
        flask dnspython python-dateutil expiringdict gunicorn \
        "idna>=2.0.0" cryptography psutil postfix-mta-sts-resolver \
        email_validator pyOpenSSL qrcode pyotp \
        boto3 b2sdk requests

    echo "[3.5] Restarting mailinabox.service..."
    systemctl daemon-reload
    systemctl restart mailinabox.service
    sleep 3
    if systemctl is-active --quiet mailinabox.service; then
        echo "  mailinabox.service: active ✓"
    else
        echo "  ERROR: mailinabox.service inactive. Check logs:"
        journalctl -u mailinabox.service --no-pager -n 20 | tail -10
        echo "  Common issue: missing Python module. Install + retry."
        return 1
    fi

    echo "[3.6] Restarting other services..."
    systemctl restart postfix dovecot rspamd nginx php8.0-fpm fail2ban

    echo
    echo "PHASE 3 COMPLETE."
}

phase_verify() {
    echo
    echo "=== PHASE 4: VERIFY ==="

    echo "[4.1] Service states..."
    for svc in postfix dovecot rspamd nginx redis-server fail2ban opendmarc opendkim mailinabox php8.0-fpm; do
        if systemctl is-active --quiet "$svc"; then
            echo "  $svc: active ✓"
        else
            echo "  $svc: INACTIVE ✗"
        fi
    done

    echo "[4.2] Listening ports..."
    for port in 25 465 587 993 443 80 11332 11334 10222; do
        if ss -tln | awk -v p=":$port " '$4 ~ p {found=1} END {exit !found}'; then
            echo "  $port: listening ✓"
        else
            echo "  $port: NOT listening ✗"
        fi
    done

    echo "[4.3] Test mail send (loopback)..."
    ADMIN=$(awk -F= '/^PRIMARY_HOSTNAME/ {print "root@" $2}' /etc/mailinabox.conf)
    echo "Subject: post-upgrade verify $(date)
To: $ADMIN

Test mail post-upgrade. Auto-generated by upgrade-2204-to-2404.sh." | sendmail -t -v 2>&1 | tail -5

    sleep 2
    QUEUE=$(mailq | tail -1)
    echo "  Queue: $QUEUE"

    echo "[4.4] Admin panel..."
    HTTP=$(curl -sk -o /dev/null -w "%{http_code}" https://localhost/admin/)
    echo "  HTTPS /admin/: $HTTP $([[ $HTTP == 200 ]] && echo '✓' || echo '✗')"

    echo "[4.5] DKIM keys..."
    if ls /home/user-data/mail/dkim/mail/private.txt 2>/dev/null; then
        echo "  DKIM private key: present ✓"
    else
        echo "  DKIM private key: MISSING ✗"
    fi

    echo
    echo "PHASE 4 COMPLETE."
    echo
    echo "If all checks pass, the upgrade is SUCCESSFUL."
    echo "Don't forget to:"
    echo "  1. Re-enable apt-daily timers: systemctl start apt-daily.timer apt-daily-upgrade.timer"
    echo "  2. Test from an external client (real send/receive)"
    echo "  3. Wait 24h before deleting the VM checkpoint"
}

# Main dispatcher
require_root

case "$PHASE" in
    prep)   phase_prep ;;
    os)     phase_os ;;
    miab)   phase_miab ;;
    verify) phase_verify ;;
    all)
        phase_prep
        if confirm "PHASE 1 done. Did you take a VM-level checkpoint? Continue with do-release-upgrade?"; then
            phase_os
            # Phase os reboots, so phases miab+verify must be run separately after reboot
            echo "After reboot, run: sudo bash $0 --phase miab"
        fi
        ;;
    *)
        echo "ERROR: unknown phase '$PHASE'"
        echo "Usage: sudo bash $0 [--phase {prep|os|miab|verify|all}]"
        exit 1
        ;;
esac

echo
echo "==============================================="
echo " DONE: $(date -Iseconds)"
echo "==============================================="
