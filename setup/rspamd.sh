#!/bin/bash
# rspamd spam filter setup for Mail-in-a-Box
# ============================================
#
# Alternative to SpamAssassin, selected via spam_filter setting in settings.yaml.
# rspamd provides:
#   - C multi-threaded scanning (scales to all CPUs)
#   - Redis-backed Bayes classifier (no file permission issues)
#   - Milter protocol integration with Postfix
#   - Web UI for monitoring on port 11334
#   - IMAPSieve-based learning via rspamc (no Perl/sa-learn overhead)
#   - Spamhaus DQS integration (optional, free tier available)
#   - Custom anti-phishing rules (display name spoofing, urgency subjects)
#   - Fuzzy hash checking (rspamd.com collaborative network)
#   - URL reputation and redirect following
#   - MX validation, ASN lookups, IP/SPF/DKIM reputation tracking
#
# Optional settings in settings.yaml:
#   spam_filter: rspamd           # activates this setup
#   spamhaus_dqs_key: <26-char>   # optional Spamhaus DQS key
#   rspamd_password: <password>   # optional Web UI password
#
# This script is sourced from setup/spamassassin.sh when spam_filter=rspamd.

source setup/functions.sh
source /etc/mailinabox.conf

# Use MiaB venv python if available (has rtyaml), fallback to system python3
MIAB_PYTHON="/usr/local/lib/mailinabox/env/bin/python3"
if [ ! -x "$MIAB_PYTHON" ]; then
	MIAB_PYTHON="python3"
fi

echo "Installing rspamd spam filter..."

# === INSTALL PACKAGES ===

apt_install rspamd redis-server

# === WORKER CONFIGURATION ===

# Normal worker: scan mail using all available CPUs
NUM_CPUS=$(nproc)
cat > /etc/rspamd/local.d/worker-normal.inc << EOF
count = $NUM_CPUS;
EOF

# Proxy worker: milter mode for Postfix integration
cat > /etc/rspamd/local.d/worker-proxy.inc << 'EOF'
milter = yes;
timeout = 120s;
upstream "local" {
    self_scan = yes;
}
bind_socket = "127.0.0.1:11332";
count = 4;
EOF

# Controller worker: Web UI + API on port 11334
# Read rspamd_password from settings.yaml (simple grep, no Python needed)
RSPAMD_PASSWORD=$(cat "$STORAGE_ROOT/settings.yaml" 2>/dev/null | grep "^rspamd_password:" | awk '{print $2}')

if [ -n "$RSPAMD_PASSWORD" ]; then
	RSPAMD_PASSWORD_HASH=$(rspamadm pw -p "$RSPAMD_PASSWORD" 2>/dev/null)
	cat > /etc/rspamd/local.d/worker-controller.inc << EOF
password = "$RSPAMD_PASSWORD_HASH";
bind_socket = "127.0.0.1:11334";
EOF
else
	cat > /etc/rspamd/local.d/worker-controller.inc << 'EOF'
bind_socket = "127.0.0.1:11334";
EOF
fi

# === BAYES CLASSIFIER (Redis backend) ===

cat > /etc/rspamd/local.d/classifier-bayes.conf << 'EOF'
backend = "redis";
servers = "127.0.0.1";
autolearn = true;
min_learns = 100;
EOF

# === REDIS CONFIGURATION ===

# Tune Redis for mail server use (memory limit, persistence)
tools/editconf.py /etc/redis/redis.conf -s \
	"bind=127.0.0.1 ::1" \
	"maxmemory=2gb" \
	"maxmemory-policy=allkeys-lru"

# === SCORING / ACTIONS ===

cat > /etc/rspamd/local.d/actions.conf << 'EOF'
reject = 15;
add_header = 5;
greylist = 4;
EOF

# === DMARC MODULE ===
# Reject/quarantine based on sender's DMARC policy

cat > /etc/rspamd/local.d/dmarc.conf << 'EOF'
reporting = false;
actions = {
    quarantine = "add_header";
    reject = "reject";
}
EOF

# === MX CHECK MODULE ===
# Reject mail from domains with invalid/missing MX records

cat > /etc/rspamd/local.d/mx_check.conf << 'EOF'
enabled = true;
timeout = 5.0;
expire = 3600;
expire_novalid = 7200;
EOF

# === ASN MODULE ===
# Look up sender's Autonomous System Number for reputation

cat > /etc/rspamd/local.d/asn.conf << 'EOF'
provider_type = "rspamd";
provider_info {
    ip4 = "asn.rspamd.com";
    ip6 = "asn6.rspamd.com";
}
expire = 86400;
EOF

# === REPUTATION MODULE ===
# Track sender reputation across IP, SPF, DKIM

cat > /etc/rspamd/local.d/reputation.conf << 'EOF'
rules {
    ip_reputation {
        selector "ip" {}
        backend "redis" {}
    }
    spf_reputation {
        selector "spf" {}
        backend "redis" {}
    }
    dkim_reputation {
        selector "dkim" {}
        backend "redis" {}
    }
}
EOF

# === URL REDIRECTOR ===
# Follow URL redirects to check actual destination

cat > /etc/rspamd/local.d/url_redirector.conf << 'EOF'
enabled = true;
expire = 86400;
nested_limit = 3;
redirectors_only = true;
EOF

# === HISTORY REDIS ===
# Store scan history in Redis for Web UI

cat > /etc/rspamd/local.d/history_redis.conf << 'EOF'
servers = "127.0.0.1";
expire = 604800;
nrows = 2000;
compress = true;
EOF

# === FUZZY CHECK ===
# Collaborative fuzzy hash network (rspamd.com, 500M+ hashes)

cat > /etc/rspamd/local.d/fuzzy_check.conf << 'EOF'
rule "rspamd.com" {
    algorithm = "mumhash";
    servers = "round-robin:fuzzy1.rspamd.com:11335,fuzzy2.rspamd.com:11335";
    encryption_key = "icy63itbhhni8bq15hc3gian8xteso1obe1hy5njaerth7okboq";
    symbol = "FUZZY_UNKNOWN";
    mime_types = ["*"];
    max_score = 20.0;
    read_only = yes;
    skip_unknown = yes;
    fuzzy_map = {
        FUZZY_DENIED {
            max_score = 20.0;
            flag = 1;
        }
        FUZZY_PROB {
            max_score = 10.0;
            flag = 2;
        }
        FUZZY_WHITE {
            max_score = 2.0;
            flag = 3;
        }
    }
}
EOF

# === SCORING OVERRIDES ===
# Tune DMARC/DKIM/SPF symbol weights

cat > /etc/rspamd/local.d/groups.conf << 'EOF'
symbols {
    "DMARC_NA" { weight = 1.0; }
    "DMARC_POLICY_REJECT" { weight = 4.0; }
    "DMARC_POLICY_QUARANTINE" { weight = 3.0; }
    "DMARC_POLICY_ALLOW" { weight = 0.0; description = "DMARC p=none is neutral, not a bonus"; }
    "R_DKIM_NA" { weight = 0.5; }
    "R_DKIM_REJECT" { weight = 3.0; }
    "R_SPF_FAIL" { weight = 3.0; }
    "R_SPF_SOFTFAIL" { weight = 2.0; }
    "R_SPF_NA" { weight = 1.0; }
}
EOF

# === COMPOSITE RULES ===
# Combine multiple weak signals into stronger detection

cat > /etc/rspamd/local.d/composites.conf << 'EOF'
SUSPICIOUS_NO_AUTH {
    expression = "R_DKIM_NA & HFILTER_HOSTNAME_UNKNOWN";
    score = 3.0;
    description = "No DKIM signature from host without reverse DNS";
}
SPAM_FRIENDLY_SETUP {
    expression = "R_DKIM_NA & HFILTER_HOSTNAME_UNKNOWN & DMARC_POLICY_ALLOW";
    score = 4.0;
    description = "No DKIM + no reverse DNS + DMARC=none (disposable spam domain)";
}
EOF

# === SPAMHAUS DQS (optional) ===
# If spamhaus_dqs_key is set in settings.yaml, configure DQS blocklists.
# DQS provides real-time access to Spamhaus ZEN, DBL, ZRD blocklists.
# Free tier: register at https://www.spamhaus.com/data-access/free-data-query-service/

DQS_KEY=$(cat "$STORAGE_ROOT/settings.yaml" 2>/dev/null | grep "^spamhaus_dqs_key:" | awk '{print $2}')

if [ -n "$DQS_KEY" ] && [ ${#DQS_KEY} -eq 26 ]; then
	echo "Configuring Spamhaus DQS with key ${DQS_KEY:0:4}...${DQS_KEY:22:4}"

	# Fix bind9 DNS resolution for Spamhaus zones.
	# MiaB uses Google DNS (8.8.8.8) as forwarders, but Spamhaus blocks queries
	# from major public resolvers. Forward Spamhaus zones via Cloudflare/Quad9.
	if ! grep -q "dq.spamhaus.net" /etc/bind/named.conf.local 2>/dev/null; then
		cat >> /etc/bind/named.conf.local << 'BINDEOF'

// Spamhaus DNS: bypass Google DNS forwarders (Spamhaus blocks queries from 8.8.8.8)
// Use Cloudflare + Quad9 which correctly resolve Spamhaus zones
zone "spamhaus.org" {
    type forward;
    forwarders { 1.1.1.1; 9.9.9.9; };
};
zone "spamhaus.net" {
    type forward;
    forwarders { 1.1.1.1; 9.9.9.9; };
};
BINDEOF
		restart_service bind9
	fi

	# RBL configuration with DQS key
	cat > /etc/rspamd/local.d/rbl.conf << RBLEOF
rbls {
    spamhaus {
        rbl = "${DQS_KEY}.zen.dq.spamhaus.net";
        from = false;
    }
    spamhaus_from {
        from = true;
        received = false;
        rbl = "${DQS_KEY}.zen.dq.spamhaus.net";
        returncodes {
            SPAMHAUS_ZEN = [ "127.0.0.2", "127.0.0.3", "127.0.0.4", "127.0.0.5", "127.0.0.6", "127.0.0.7", "127.0.0.9", "127.0.0.10", "127.0.0.11" ];
        }
    }
    spamhaus_authbl_received {
        rbl = "${DQS_KEY}.authbl.dq.spamhaus.net";
        from = false;
        received = true;
        ipv6 = true;
        returncodes {
            SH_AUTHBL_RECEIVED = "127.0.0.20"
        }
    }
    spamhaus_dbl {
        rbl = "${DQS_KEY}.dbl.dq.spamhaus.net";
        helo = true;
        rdns = true;
        dkim = true;
        disable_monitoring = true;
        returncodes {
            RBL_DBL_SPAM = "127.0.1.2";
            RBL_DBL_PHISH = "127.0.1.4";
            RBL_DBL_MALWARE = "127.0.1.5";
            RBL_DBL_BOTNET = "127.0.1.6";
            RBL_DBL_ABUSED_SPAM = "127.0.1.102";
            RBL_DBL_ABUSED_PHISH = "127.0.1.104";
            RBL_DBL_ABUSED_MALWARE = "127.0.1.105";
            RBL_DBL_ABUSED_BOTNET = "127.0.1.106";
            RBL_DBL_DONT_QUERY_IPS = "127.0.1.255";
        }
    }
    spamhaus_dbl_fullurls {
        ignore_defaults = true;
        no_ip = true;
        rbl = "${DQS_KEY}.dbl.dq.spamhaus.net";
        selector = 'urls:get_host'
        disable_monitoring = true;
        returncodes {
            DBLABUSED_SPAM_FULLURLS = "127.0.1.102";
            DBLABUSED_PHISH_FULLURLS = "127.0.1.104";
            DBLABUSED_MALWARE_FULLURLS = "127.0.1.105";
            DBLABUSED_BOTNET_FULLURLS = "127.0.1.106";
        }
    }
    spamhaus_zrd {
        rbl = "${DQS_KEY}.zrd.dq.spamhaus.net";
        helo = true;
        rdns = true;
        dkim = true;
        disable_monitoring = true;
        returncodes {
            RBL_ZRD_VERY_FRESH_DOMAIN = ["127.0.2.2", "127.0.2.3", "127.0.2.4"];
            RBL_ZRD_FRESH_DOMAIN = ["127.0.2.5", "127.0.2.6", "127.0.2.7", "127.0.2.8", "127.0.2.9", "127.0.2.10", "127.0.2.11", "127.0.2.12", "127.0.2.13", "127.0.2.14", "127.0.2.15", "127.0.2.16", "127.0.2.17", "127.0.2.18", "127.0.2.19", "127.0.2.20", "127.0.2.21", "127.0.2.22", "127.0.2.23", "127.0.2.24"];
            RBL_ZRD_DONT_QUERY_IPS = "127.0.2.255";
        }
    }
    "SPAMHAUS_ZEN_URIBL" {
        rbl = "${DQS_KEY}.zen.dq.spamhaus.net";
        resolve_ip = true;
        replyto = true;
        emails = true;
        emails_domainonly = true;
        returncodes {
            URIBL_SBL = "127.0.0.2";
            URIBL_SBL_CSS = "127.0.0.3";
            URIBL_XBL = ["127.0.0.4", "127.0.0.5", "127.0.0.6", "127.0.0.7"];
            URIBL_PBL = ["127.0.0.10", "127.0.0.11"];
            URIBL_DROP = "127.0.0.9";
        }
    }
    SH_EMAIL_DBL {
        ignore_defaults = true;
        replyto = true;
        emails_domainonly = true;
        disable_monitoring = true;
        rbl = "${DQS_KEY}.dbl.dq.spamhaus.net"
        returncodes = {
            SH_EMAIL_DBL = ["127.0.1.2", "127.0.1.4", "127.0.1.5", "127.0.1.6"];
            SH_EMAIL_DBL_ABUSED = ["127.0.1.102", "127.0.1.104", "127.0.1.105", "127.0.1.106"];
            SH_EMAIL_DBL_DONT_QUERY_IPS = [ "127.0.1.255" ];
        }
    }
    SH_EMAIL_ZRD {
        ignore_defaults = true;
        replyto = true;
        emails_domainonly = true;
        disable_monitoring = true;
        rbl = "${DQS_KEY}.zrd.dq.spamhaus.net"
        returncodes = {
            SH_EMAIL_ZRD_VERY_FRESH_DOMAIN = ["127.0.2.2", "127.0.2.3", "127.0.2.4"];
            SH_EMAIL_ZRD_FRESH_DOMAIN = ["127.0.2.5", "127.0.2.6", "127.0.2.7", "127.0.2.8", "127.0.2.9", "127.0.2.10", "127.0.2.11", "127.0.2.12", "127.0.2.13", "127.0.2.14", "127.0.2.15", "127.0.2.16", "127.0.2.17", "127.0.2.18", "127.0.2.19", "127.0.2.20", "127.0.2.21", "127.0.2.22", "127.0.2.23", "127.0.2.24"];
            SH_EMAIL_ZRD_DONT_QUERY_IPS = [ "127.0.2.255" ];
        }
    }
    "DBL" {
        rbl = "${DQS_KEY}.dbl.dq.spamhaus.net";
        disable_monitoring = true;
    }
    "ZRD" {
        ignore_defaults = true;
        rbl = "${DQS_KEY}.zrd.dq.spamhaus.net";
        no_ip = true;
        dkim = true;
        emails = true;
        emails_domainonly = true;
        urls = true;
        returncodes = {
            ZRD_VERY_FRESH_DOMAIN = ["127.0.2.2", "127.0.2.3", "127.0.2.4"];
            ZRD_FRESH_DOMAIN = ["127.0.2.5", "127.0.2.6", "127.0.2.7", "127.0.2.8", "127.0.2.9", "127.0.2.10", "127.0.2.11", "127.0.2.12", "127.0.2.13", "127.0.2.14", "127.0.2.15", "127.0.2.16", "127.0.2.17", "127.0.2.18", "127.0.2.19", "127.0.2.20", "127.0.2.21", "127.0.2.22", "127.0.2.23", "127.0.2.24"];
        }
    }
}
RBLEOF

	# DQS scoring
	cat > /etc/rspamd/local.d/rbl_group.conf << 'GRPEOF'
symbols = {
    "SPAMHAUS_ZEN" { weight = 7.0; }
    "SH_AUTHBL_RECEIVED" { weight = 4.0; }
    "RBL_DBL_SPAM" { weight = 7.0; }
    "RBL_DBL_PHISH" { weight = 7.0; }
    "RBL_DBL_MALWARE" { weight = 7.0; }
    "RBL_DBL_BOTNET" { weight = 7.0; }
    "RBL_DBL_ABUSED_SPAM" { weight = 3.0; }
    "RBL_DBL_ABUSED_PHISH" { weight = 3.0; }
    "RBL_DBL_ABUSED_MALWARE" { weight = 3.0; }
    "RBL_DBL_ABUSED_BOTNET" { weight = 3.0; }
    "RBL_ZRD_VERY_FRESH_DOMAIN" { weight = 7.0; }
    "RBL_ZRD_FRESH_DOMAIN" { weight = 4.0; }
    "ZRD_VERY_FRESH_DOMAIN" { weight = 7.0; }
    "ZRD_FRESH_DOMAIN" { weight = 4.0; }
    "SH_EMAIL_DBL" { weight = 7.0; }
    "SH_EMAIL_DBL_ABUSED" { weight = 7.0; }
    "SH_EMAIL_ZRD_VERY_FRESH_DOMAIN" { weight = 7.0; }
    "SH_EMAIL_ZRD_FRESH_DOMAIN" { weight = 4.0; }
    "RBL_DBL_DONT_QUERY_IPS" { weight = 0.0; }
    "RBL_ZRD_DONT_QUERY_IPS" { weight = 0.0; }
    "SH_EMAIL_ZRD_DONT_QUERY_IPS" { weight = 0.0; }
    "SH_EMAIL_DBL_DONT_QUERY_IPS" { weight = 0.0; }
    "DBLABUSED_SPAM_FULLURLS" { weight = 5.5; }
    "DBLABUSED_PHISH_FULLURLS" { weight = 5.5; }
    "DBLABUSED_MALWARE_FULLURLS" { weight = 5.5; }
    "DBLABUSED_BOTNET_FULLURLS" { weight = 5.5; }
    "URIBL_SBL" { weight = 6.5; one_shot = true; }
    "URIBL_SBL_CSS" { weight = 6.5; one_shot = true; }
    "URIBL_PBL" { weight = 0.01; one_shot = true; }
    "URIBL_DROP" { weight = 6.5; one_shot = true; }
    "URIBL_XBL" { weight = 5.0; one_shot = true; }
}
GRPEOF

	echo "Spamhaus DQS configured successfully."
else
	if [ -n "$DQS_KEY" ]; then
		echo "WARNING: Spamhaus DQS key must be exactly 26 characters (got ${#DQS_KEY}). Skipping DQS."
	fi
	# Clean up DQS configs if key removed
	rm -f /etc/rspamd/local.d/rbl.conf /etc/rspamd/local.d/rbl_group.conf
fi

# === CUSTOM ANTI-PHISHING RULES ===

cat > /etc/rspamd/rspamd.local.lua << 'LUAEOF'
-- Custom rspamd rules for Mail-in-a-Box
-- Anti-phishing and anti-spoofing detection

local rspamd_logger = require "rspamd_logger"

-- RULE 1: Display name spoofing detection
-- Catches: "geseidl.ro" <admin@parketing.si> -> robert.popa@geseidl.ro
-- The From display name contains the recipient's domain but the actual
-- sender address is from a completely different domain.
rspamd_config.FROM_NAME_SPOOFS_RCPT_DOMAIN = {
  callback = function(task)
    local from = task:get_from('mime')
    if not from or not from[1] or not from[1].name then return false end
    local from_name = from[1].name:lower()
    local from_addr = (from[1].addr or ''):lower()
    local from_domain = from_addr:match('@(.+)$') or ''

    local rcpt_domains = {}
    local smtp_rcpts = task:get_recipients('smtp')
    if smtp_rcpts then
      for _, rcpt in ipairs(smtp_rcpts) do
        local d = (rcpt.addr or ''):lower():match('@(.+)$')
        if d then rcpt_domains[d] = true end
      end
    end
    local mime_rcpts = task:get_recipients('mime')
    if mime_rcpts then
      for _, rcpt in ipairs(mime_rcpts) do
        local d = (rcpt.addr or ''):lower():match('@(.+)$')
        if d then rcpt_domains[d] = true end
      end
    end

    for rcpt_domain, _ in pairs(rcpt_domains) do
      if from_name:find(rcpt_domain, 1, true)
         and from_domain ~= rcpt_domain then
        return true, 1.0, from_name .. ' -> ' .. rcpt_domain
      end
    end
    return false
  end,
  score = 8.0,
  description = 'From display name contains recipient domain but sender is external (spoofing)',
  group = 'phishing',
}

-- RULE 2: Subject urgency phishing patterns
-- Common social engineering tactics in subject lines
rspamd_config.SUBJ_URGENCY_PHISH = {
  callback = function(task)
    local subj_raw = task:get_subject()
    if not subj_raw then return false end
    local subj = subj_raw:lower()
    local patterns = {
      'action required', 'immediate action',
      'account.+suspend', 'account.+delet', 'account.+terminat',
      'account.+locked', 'account.+disabled',
      'mailbox.+full', 'mailbox.+update', 'mailbox.+expir',
      'password.+expir', 'verify.+account', 'confirm.+identity',
      'unusual.+activity', 'unauthorized.+access',
      'security.+alert', 'scheduled.+for.+deletion',
    }
    for _, pat in ipairs(patterns) do
      if subj:find(pat) then
        return true, 1.0, pat
      end
    end
    return false
  end,
  score = 4.0,
  description = 'Subject matches common phishing urgency patterns',
  group = 'phishing',
}

-- RULE 3: Phishing keywords in URLs
rspamd_config.URL_PHISH_KEYWORDS = {
  callback = function(task)
    local urls = task:get_urls()
    if not urls then return false end
    local suspicious = {
      'phish', 'pharming', 'credential', 'chameleon',
      'capturelogin', 'securepage', 'confirmemail',
      'loginverif', 'abortsecur', 'abortsafe',
    }
    for _, url in ipairs(urls) do
      local host = (url:get_host() or ''):lower()
      local path = (url:get_path() or ''):lower()
      local full = host .. '/' .. path
      for _, keyword in ipairs(suspicious) do
        if full:find(keyword, 1, true) then
          return true, 1.0, keyword .. ' in ' .. host
        end
      end
    end
    return false
  end,
  score = 6.0,
  description = 'URL contains phishing-related keywords',
  group = 'phishing',
}

-- RULE 4: No DKIM + No DMARC = suspicious
-- Legitimate senders almost always have at least DKIM or DMARC
rspamd_config.NO_DKIM_NO_DMARC = {
  callback = function(task)
    local dmarc_na = task:get_symbol('DMARC_NA')
    local dkim_na = task:get_symbol('R_DKIM_NA')
    if dmarc_na and dkim_na then
      return true
    end
    return false
  end,
  score = 2.0,
  description = 'No DKIM signature and no DMARC policy (unsigned, unverified)',
  group = 'policy',
}
LUAEOF

# === MILTER HEADERS ===
# Produce X-Spam-Status header compatible with existing Dovecot sieve rules
# that check: header :regex "X-Spam-Status" "^Yes"

cat > /etc/rspamd/local.d/milter_headers.conf << 'EOF'
use = ["x-spamd-bar", "x-spam-status", "x-spam-level", "authentication-results"];
skip_local = false;
skip_authenticated = true;

routines {
  x-spam-status {
    header = "X-Spam-Status";
    remove = 1;
  }
  x-spamd-bar {
    header = "X-Spamd-Bar";
    positive = "+";
    negative = "-";
    neutral = "/";
    remove = 1;
  }
  authentication-results {
    header = "Authentication-Results";
    remove = 0;
    add_smtp_user = false;
  }
}
EOF

# === DKIM SIGNING ===
# Keep OpenDKIM for DKIM signing (simpler migration). rspamd still validates
# DKIM on incoming mail. Disable rspamd's own signing to avoid conflicts.

cat > /etc/rspamd/local.d/dkim_signing.conf << 'EOF'
enabled = false;
EOF

# === PHISHING / URL CHECKS ===

cat > /etc/rspamd/local.d/phishing.conf << 'EOF'
openphish_enabled = true;
phishtank_enabled = true;
EOF

# === REPLIES MODULE ===
# Whitelist replies to messages sent from our server

cat > /etc/rspamd/local.d/replies.conf << 'EOF'
action = "no action";
expire = 86400;
EOF

# === MULTIMAP (whitelist/blacklist from settings.yaml) ===

WHITELIST_FILE="/etc/rspamd/local.d/whitelist-domains.map"
BLACKLIST_FILE="/etc/rspamd/local.d/blacklist-domains.map"
touch "$WHITELIST_FILE" "$BLACKLIST_FILE"

# Generate whitelist/blacklist map files from settings.yaml
$MIAB_PYTHON << PYEOF
import sys, os
sys.path.insert(0, os.path.join('$PWD', 'management'))
from utils import load_settings, load_environment
env = load_environment()
settings = load_settings(env)
wl = settings.get('spam_whitelist', [])
bl = settings.get('spam_blacklist', [])
with open('$WHITELIST_FILE', 'w') as f:
    f.write('\n'.join(wl) + '\n' if wl else '')
with open('$BLACKLIST_FILE', 'w') as f:
    f.write('\n'.join(bl) + '\n' if bl else '')
PYEOF

cat > /etc/rspamd/local.d/multimap.conf << EOF
WHITELIST_SENDER_DOMAIN {
    type = "from";
    map = "$WHITELIST_FILE";
    score = -10.0;
    description = "Whitelisted sender (MiaB admin)";
}

BLACKLIST_SENDER_DOMAIN {
    type = "from";
    map = "$BLACKLIST_FILE";
    score = 10.0;
    description = "Blacklisted sender (MiaB admin)";
}
EOF

# === DOVECOT IMAPSIEVE (learn spam/ham from user actions) ===
# When a user moves mail to/from Spam folder, train rspamd via rspamc

cat > /etc/dovecot/conf.d/90-imapsieve.conf << 'EOF'
protocol imap {
  mail_plugins = $mail_plugins imap_sieve
}

plugin {
  sieve_plugins = sieve_imapsieve sieve_extprograms
  sieve_global_extensions = +vnd.dovecot.pipe +vnd.dovecot.environment

  imapsieve_mailbox1_name = Spam
  imapsieve_mailbox1_causes = COPY APPEND
  imapsieve_mailbox1_before = file:/etc/dovecot/sieve/learn-spam.sieve

  imapsieve_mailbox2_name = *
  imapsieve_mailbox2_from = Spam
  imapsieve_mailbox2_causes = COPY
  imapsieve_mailbox2_before = file:/etc/dovecot/sieve/learn-ham.sieve

  sieve_pipe_bin_dir = /etc/dovecot/sieve
}
EOF

mkdir -p /etc/dovecot/sieve
# Sieve directory must be writable by the mail user so Dovecot can
# compile and cache .svbin binaries at runtime.
chown mail:dovecot /etc/dovecot/sieve
chmod 775 /etc/dovecot/sieve

# Dovecot's systemd unit uses ProtectSystem=full which mounts /etc read-only.
# We need an override to allow writing compiled sieve binaries.
mkdir -p /etc/systemd/system/dovecot.service.d
cat > /etc/systemd/system/dovecot.service.d/sieve-write.conf << 'EOF'
[Service]
ReadWritePaths=/etc/dovecot/sieve
EOF
systemctl daemon-reload

cat > /etc/dovecot/sieve/learn-spam.sieve << 'EOF'
require ["vnd.dovecot.pipe", "copy", "imapsieve", "environment", "variables"];
pipe :copy "rspamd-learn.sh" ["spam"];
EOF

cat > /etc/dovecot/sieve/learn-ham.sieve << 'EOF'
require ["vnd.dovecot.pipe", "copy", "imapsieve", "environment", "variables"];

# imap.mailbox = destination folder when moving FROM Spam.
# Skip learn_ham when user deletes spam (moves Spam -> Trash).
if environment :is "imap.mailbox" "Trash" {
    stop;
}

pipe :copy "rspamd-learn.sh" ["ham"];
EOF

# Learn script: lightweight rspamc call (no Perl overhead like sa-learn)
cat > /etc/dovecot/sieve/rspamd-learn.sh << 'LEARNEOF'
#!/bin/bash
# rspamd learning script for Dovecot IMAPSieve
# Called when users move messages to/from Spam folder
exec /usr/bin/rspamc learn_"$1"
LEARNEOF
chmod +x /etc/dovecot/sieve/rspamd-learn.sh

# Sieve scripts are compiled automatically by Dovecot at runtime when
# the sieve_extprograms and sieve_imapsieve plugins are loaded.
# Manual sievec compilation fails because it doesn't load these plugins.

# === REMOVE DEPRECATED DOVECOT ANTISPAM PLUGIN ===

# Remove antispam plugin from mail_plugins (used by SpamAssassin setup)
sed -i 's/ antispam//' /etc/dovecot/conf.d/20-imap.conf 2>/dev/null
sed -i 's/ antispam//' /etc/dovecot/conf.d/20-pop3.conf 2>/dev/null
# Remove the SpamAssassin-specific dovecot config
rm -f /etc/dovecot/conf.d/99-local-spampd.conf

# === DISABLE SPAMASSASSIN ===

systemctl stop spampd 2>/dev/null
systemctl disable spampd 2>/dev/null
systemctl stop spamassassin 2>/dev/null
systemctl disable spamassassin 2>/dev/null

# === INITIAL BAYES TRAINING ===
# Seed the Bayes classifier from existing mailboxes.
# Sources: INBOX → ham, .Spam + .Trash → spam
# Only runs significant training on first setup (min_learns=100 threshold).

if [ -d "$STORAGE_ROOT/mail/mailboxes" ]; then
	BAYES_SPAM=$(rspamc stat 2>/dev/null | grep "BAYES_SPAM" | awk '{print $NF}')
	if [ "${BAYES_SPAM:-0}" -lt 100 ]; then
		echo "Training rspamd Bayes from existing mailboxes..."
		# Ham: recent messages in INBOX (last 6 months, max 10000)
		find "$STORAGE_ROOT/mail/mailboxes" -path "*/cur/*" \
			! -path "*/.Spam/*" ! -path "*/.Trash/*" ! -path "*/.Drafts/*" \
			-type f -mtime -180 -print0 2>/dev/null | \
			head -z -n 10000 | xargs -0 -P8 -I{} rspamc learn_ham {} 2>/dev/null
		# Spam: messages in .Spam and .Trash directories (all of them)
		find "$STORAGE_ROOT/mail/mailboxes" \( -path "*/.Spam/cur/*" -o -path "*/.Trash/cur/*" \) \
			-type f -print0 2>/dev/null | \
			head -z -n 10000 | xargs -0 -P8 -I{} rspamc learn_spam {} 2>/dev/null
		echo "Bayes training complete."
	fi
fi

# === START SERVICES ===

restart_service redis-server
restart_service rspamd
restart_service dovecot
