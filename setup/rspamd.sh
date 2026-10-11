#!/bin/bash
# rspamd spam filter setup for Mail-in-a-Box
# Sourced from setup/spamassassin.sh when spam_filter=rspamd.

source setup/functions.sh
source /etc/mailinabox.conf

# Use MiaB venv python if available, fallback to system python3
MIAB_PYTHON="/usr/local/lib/mailinabox/env/bin/python3"
if [ ! -x "$MIAB_PYTHON" ]; then
	MIAB_PYTHON="python3"
fi

echo "Installing rspamd spam filter..."

# === INSTALL PACKAGES ===

# Official rspamd.com apt repo: Ubuntu noble ships rspamd 3.8.x, but the gpt
# module (secondary LLM spam filter) needs rspamd >= 3.9. Production
# runs 4.1.0 from this repo since 2026-06-11.
mkdir -p /etc/apt/keyrings
if [ ! -f /etc/apt/keyrings/rspamd.gpg ]; then
	wget -qO- https://rspamd.com/apt-stable/gpg.key | gpg --dearmor > /etc/apt/keyrings/rspamd.gpg
fi
echo "deb [signed-by=/etc/apt/keyrings/rspamd.gpg] http://rspamd.com/apt-stable/ $(lsb_release -cs) main" > /etc/apt/sources.list.d/rspamd.list
hide_output apt-get update

apt_install rspamd redis-server

# === WORKER CONFIGURATION ===

# Normal worker
NUM_CPUS=$(nproc)
cat > /etc/rspamd/local.d/worker-normal.inc << EOF
count = $NUM_CPUS;
EOF

# Proxy worker: milter mode for Postfix
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
RSPAMD_PASSWORD=$(cat "$STORAGE_ROOT/settings.yaml" 2>/dev/null | grep "^rspamd_password:" | awk '{print $2}')

# Auto-generate controller password if not set
if [ -z "$RSPAMD_PASSWORD" ]; then
	RSPAMD_PASSWORD=$(openssl rand -base64 24)
	$MIAB_PYTHON << PYEOF
import sys, os
sys.path.insert(0, os.path.join('$PWD', 'management'))
from utils import load_settings, write_settings, load_environment
env = load_environment()
settings = load_settings(env)
settings['rspamd_password'] = '$RSPAMD_PASSWORD'
write_settings(settings, env)
PYEOF
fi

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

# === BAYES CLASSIFIER ===

cat > /etc/rspamd/local.d/classifier-bayes.conf << 'EOF'
name = "bayes_geseidl_20260818";
backend = "redis";
servers = "127.0.0.1";
database = 14;
new_schema = true;
store_tokens = false;
signatures = false;
# Folder moves are the explicit source of Bayes labels. Automatic learning can
# turn a transient scoring/model error into a persistent feedback loop.
autolearn = false;
min_tokens = 11;
min_learns = 200;
tokenizer { name = "osb"; }
cache { }
statfile {
  symbol = "BAYES_HAM";
  spam = false;
}
statfile {
  symbol = "BAYES_SPAM";
  spam = true;
}
EOF

# === REDIS CONFIGURATION ===

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

# === MILTER HEADERS ===
# X-Spam-Status compatible with existing Dovecot sieve rules

cat > /etc/rspamd/local.d/milter_headers.conf << 'EOF'
use = ["x-spamd-bar", "x-spam-status", "x-spamd-result", "x-spam-level", "authentication-results"];
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
  x-spamd-result {
    header = "X-Spamd-Result";
    remove = 1;
  }
  x-spam-level {
    header = "X-Spam-Level";
    char = "*";
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
# Disable rspamd signing; OpenDKIM handles DKIM.

cat > /etc/rspamd/local.d/dkim_signing.conf << 'EOF'
enabled = false;
EOF

# === PHISHING / URL CHECKS ===

cat > /etc/rspamd/local.d/phishing.conf << 'EOF'
openphish_enabled = true;
phishtank_enabled = true;
EOF

# === REPLIES MODULE ===

cat > /etc/rspamd/local.d/replies.conf << 'EOF'
action = "no action";
expire = 86400;
EOF

# === MULTIMAP (whitelist/blacklist) ===

WHITELIST_FILE="/etc/rspamd/local.d/whitelist-domains.map"
BLACKLIST_FILE="/etc/rspamd/local.d/blacklist-domains.map"
touch "$WHITELIST_FILE" "$BLACKLIST_FILE"

# Geseidl baseline whitelist seed — domenii client/infra care TREBUIE sa
# supravietuiasca regenerarii hartii din settings.yaml. Incident 2026-06-23:
# `sudo mailinabox` (full setup) a regenerat harta din settings.yaml fara cheia
# spam_whitelist -> utcb.ro pierdut. Seed-ul se uneste (dedup) cu lista din admin UI.
$MIAB_PYTHON << PYEOF
import sys, os
sys.path.insert(0, os.path.join('$PWD', 'management'))
from utils import load_settings, load_environment
env = load_environment()
settings = load_settings(env)
GESEIDL_WL_SEED = ['utcb.ro', 'seo.geseidl@gmail.com', 'artsani-energy.ro']
wl = list(dict.fromkeys((settings.get('spam_whitelist', []) or []) + GESEIDL_WL_SEED))
bl = settings.get('spam_blacklist', []) or []
with open('$WHITELIST_FILE', 'w') as f:
    f.write('\n'.join(wl) + '\n' if wl else '')
with open('$BLACKLIST_FILE', 'w') as f:
    f.write('\n'.join(bl) + '\n' if bl else '')
PYEOF

# Brand impersonation + RO phishing subject framework (geseidl-edition)
BRAND_DISPLAY_MAP="/etc/rspamd/local.d/brand_display.map"
BRAND_REAL_MAP="/etc/rspamd/local.d/brand_real_domains.map"
COURIER_DISPLAY_MAP="/etc/rspamd/local.d/courier_display.map"
COURIER_REAL_MAP="/etc/rspamd/local.d/courier_real_domains.map"
RO_PHISH_SUBJ_MAP="/etc/rspamd/local.d/ro_phish_subjects.map"
NON_RO_TLD_MAP="/etc/rspamd/local.d/non_ro_tld.map"
GESEIDL_CONTENT_RULES="/etc/rspamd/local.d/geseidl-content-rules.cf"
APPROVED_CORRESPONDENT_MAP="/etc/rspamd/local.d/approved_client_correspondents.map"
touch "$APPROVED_CORRESPONDENT_MAP"
[ -f "$COURIER_DISPLAY_MAP" ] || cat > "$COURIER_DISPLAY_MAP" << 'MAPEOF'
/(?i)(DHL|DPD|FanCourier|FAN Courier|GLS|Sameday|Nemo|Urgent\s*Cargus|Cargus|Posta Romana|PostaRomana|UPS|FedEx|TNT)\s*(RO|Romania|ROMANIA|Express)/
/(?i)Adrian\s+Cristea\s*\(DHL/
MAPEOF
[ -f "$COURIER_REAL_MAP" ] || cat > "$COURIER_REAL_MAP" << 'MAPEOF'
dhl.com
dhl.ro
mydhl.com
dhlexpress.com
dpd.com
dpd.ro
fancourier.ro
fan-courier.ro
gls-romania.ro
gls-group.eu
sameday.ro
urgentcargus.ro
cargus.ro
posta-romana.ro
postaromana.ro
ups.com
ups.ro
fedex.com
fedex.ro
tnt.com
MAPEOF
[ -f "$RO_PHISH_SUBJ_MAP" ] || cat > "$RO_PHISH_SUBJ_MAP" << 'MAPEOF'
/(?i)^Declaratiile\s+din\s+atasament\s+completate\s+si\s+semnate/
/(?i)Declaratii.*atasament.*semnate/
/(?i)^Factura\s+restanta\s+neplatita/
/(?i)^Documente\s+atasate\s+spre\s+aprobare/
MAPEOF

# Brand impersonation map (extended beyond couriers: banks, ANAF, utilities, big-tech)
# Deployed as empty placeholders here; production fill via provision copy of the
# operator's own brand_display.map + brand_real_domains.map.
[ -f "$BRAND_DISPLAY_MAP" ] || cp "$COURIER_DISPLAY_MAP" "$BRAND_DISPLAY_MAP" 2>/dev/null || touch "$BRAND_DISPLAY_MAP"
[ -f "$BRAND_REAL_MAP" ] || cp "$COURIER_REAL_MAP" "$BRAND_REAL_MAP" 2>/dev/null || touch "$BRAND_REAL_MAP"
[ -f "$NON_RO_TLD_MAP" ] || cat > "$NON_RO_TLD_MAP" << 'MAPEOF'
/@[^>]+\.(com|net|org|info|biz|xyz|top|click|online|site|fun|live|rs|tr|bg|hu|ua|ru|cn|in|pk|ng|ph|br|mx|vn|id|th|ke|za|ng|ma|eg)$/
MAPEOF

# High-confidence multilingual advance-fee fraud. The component atoms are
# unscored and only the strict conjunction contributes to the metric. This is
# intentionally deterministic: obvious scams must not consume the LLM.
cat > "$GESEIDL_CONTENT_RULES" << 'RULEEOF'
body GES_ADV_FEE_AMOUNT m{(?:\b(?:USD|EUR)\b\s*[$€]?\s*[0-9][0-9., ]{4,}|[$€]\s*[0-9][0-9., ]{4,}|[0-9][0-9., ]{4,}\s*(?:USD|EUR|d[oó]lares?|euros?)|\b(?:million|millions|milh[aã]o|milh[oõ]es|milioane?)\b)}iu
body GES_ADV_FEE_PROMISE m{\b(?:benefici[aá]r(?:io|y)?|grant|compens[aá](?:tion|t|ç[aã]o|-l[oa])?|inheritance|lottery|funds?\s+(?:release|transfer)|eliberarea\s+unui\s+grant|primi(?:rea)?\s+fondul|cart[aã]o\s+visa|visa\s+card|atm\s+card|bank\s+director|diretor\s+executivo(?:\s+do)?\s+[^\r\n]{0,80}\bbank)\b}iu
body GES_ADV_FEE_BANK m{\b(?:ora\s+bank|bank\s+of\s+africa|banca\s+european[aă]\s+de\s+investi[țt]ii|european\s+investment\s+bank|bank\s+director|diretor\s+executivo(?:\s+do)?\s+[^\r\n]{0,80}\bbank|cart[aã]o\s+visa|visa\s+card|atm\s+card)\b}iu
body GES_BODY_FREEMAIL_CONTACT m{\b[A-Z0-9._%+-]+@(?:gmail|googlemail|outlook|hotmail|yahoo)\.(?:com|ro)\b}iu
body GES_PII_FULL_NAME m{\b(?:full\s+name|nome\s+completo|numele\s+complet)\b}iu
body GES_PII_ID_DOCUMENT m{\b(?:passport|passaporte|identity\s+(?:card|document)|documento\s+de\s+identidade|carte\s+de\s+identitate)\b}iu
body GES_PII_PHONE m{\b(?:phone|telephone|telefone|num[aă]r(?:ul)?\s+de\s+telefon)\b}iu
body GES_PII_COUNTRY m{\b(?:country|pa[ií]s|[țt]ara)\b}iu
meta GES_ADVANCE_FEE_SCAM GES_ADV_FEE_AMOUNT & GES_ADV_FEE_PROMISE & ((GES_ADV_FEE_BANK & (GES_PII_PHONE | GES_BODY_FREEMAIL_CONTACT)) | (GES_PII_FULL_NAME & (GES_PII_ID_DOCUMENT | (GES_PII_PHONE & GES_PII_COUNTRY))))
header GES_TRANSACTION_ACK_SUBJECT Subject =~ /(?:Formularul\s+dvs\.?\s+a\s+fost\s+[iî]nregistrat|Comanda\s+(?:ta|dvs\.?).{0,100}a\s+fost\s+[iî]nregistrat)/iu
header GES_AUTO_REPLIED Auto-Submitted =~ /auto-replied/i
meta GES_SOLICITED_TRANSACTION_ACK GES_TRANSACTION_ACK_SUBJECT & GES_AUTO_REPLIED & !HAS_LIST_UNSUB & !MAILLIST
score GES_ADV_FEE_AMOUNT 0.0
score GES_ADV_FEE_PROMISE 0.0
score GES_ADV_FEE_BANK 0.0
score GES_BODY_FREEMAIL_CONTACT 0.0
score GES_PII_FULL_NAME 0.0
score GES_PII_ID_DOCUMENT 0.0
score GES_PII_PHONE 0.0
score GES_PII_COUNTRY 0.0
score GES_ADVANCE_FEE_SCAM 9.0
score GES_TRANSACTION_ACK_SUBJECT 0.0
score GES_AUTO_REPLIED 0.0
score GES_SOLICITED_TRANSACTION_ACK -7.0
describe GES_ADVANCE_FEE_SCAM High-confidence multilingual advance-fee scam requesting identity details
describe GES_SOLICITED_TRANSACTION_ACK Narrow solicited transactional acknowledgement, never list marketing
RULEEOF

cat > /etc/rspamd/local.d/multimap.conf << EOF
GESEIDL_CONTENT_RULES {
    type = "regexp_rules";
    map = "$GESEIDL_CONTENT_RULES";
    description = "High-confidence multilingual business-mail abuse rules";
}

APPROVED_CLIENT_CORRESPONDENT {
    type = "selector";
    selector = "from('mime'):addr.lower;rcpts('smtp'):addr.lower";
    delimiter = "|";
    map = "$APPROVED_CORRESPONDENT_MAP";
    score = 0.0;
    description = "Approved exact external-sender to GESEIDL-mailbox relationship";
}

WHITELIST_SENDER_DOMAIN {
    type = "from";
    map = "$WHITELIST_FILE";
    score = -2.0;
    description = "Explicit admin allowlist (bounded reputation signal only)";
}

BLACKLIST_SENDER_DOMAIN {
    type = "from";
    map = "$BLACKLIST_FILE";
    score = 10.0;
    description = "Blacklisted sender (MiaB admin)";
}

BRAND_DISPLAY_MATCH {
    type = "header";
    header = "From";
    filter = "email:name";
    regexp = true;
    map = "$BRAND_DISPLAY_MAP";
    score = 0.01;
    description = "Brand/institution name in From display";
}

BRAND_SUBJECT_MATCH {
    type = "header";
    header = "Subject";
    regexp = true;
    map = "$BRAND_DISPLAY_MAP";
    score = 0.01;
    description = "Brand/institution name in Subject";
}

WHITELIST_BRAND_DOMAIN {
    type = "from";
    filter = "email:domain:tld";
    map = "$BRAND_REAL_MAP";
    score = 0.0;
    description = "Authenticated brand-domain identity condition; never a ham bonus";
}

FROM_NON_RO_TLD {
    type = "header";
    header = "From";
    regexp = true;
    map = "$NON_RO_TLD_MAP";
    score = 0.0;
    description = "Sender domain is non-.ro TLD (informational)";
}

COURIER_IMPERSONATION_DISPLAY {
    type = "header";
    header = "From";
    filter = "email:name";
    regexp = true;
    map = "$COURIER_DISPLAY_MAP";
    score = 0.01;
    description = "Courier name in display name (composite input only)";
}

WHITELIST_COURIER_DOMAIN {
    type = "from";
    filter = "email:domain:tld";
    map = "$COURIER_REAL_MAP";
    score = 0.0;
    description = "Legitimate courier-domain identity condition; never a ham bonus";
}

RO_PHISH_SUBJECT {
    type = "header";
    header = "Subject";
    regexp = true;
    map = "$RO_PHISH_SUBJ_MAP";
    score = 4.0;
    description = "Subject matches known RO phishing wave";
}

EOF

# Keep the local whitelist module free from traffic-derived correspondence.
# Historic traffic, domain authentication, and volume cannot prove that an
# incoming message is wanted business correspondence. Candidate reports and
# approved per-sender/per-recipient relationships are maintained outside this
# generator; neither may move mail or bypass Rspamd/GPT automatically.
cat > /etc/rspamd/local.d/whitelist.conf << 'EOF'
# No traffic-derived client whitelist rules.
EOF

# Composites for brand impersonation + foreign-origin RO phishing
cat > /etc/rspamd/local.d/composites.conf << 'CEOF'
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

BRAND_IMPERSONATION {
    expression = "BRAND_DISPLAY_MATCH & !WHITELIST_BRAND_DOMAIN & !LOCAL_OUTBOUND & (FREEMAIL_FROM | R_DKIM_REJECT | R_SPF_FAIL | DMARC_POLICY_REJECT)";
    score = 5.0;
    description = "Brand identity claimed from freemail or with failed sender authentication";
}

COURIER_IMPERSONATION {
    expression = "COURIER_IMPERSONATION_DISPLAY & !WHITELIST_COURIER_DOMAIN & !LOCAL_OUTBOUND & (FREEMAIL_FROM | R_DKIM_REJECT | R_SPF_FAIL | DMARC_POLICY_REJECT)";
    score = 5.0;
    description = "Courier identity claimed from freemail or with failed sender authentication";
}

FOREIGN_PHISH_RO {
    expression = "R_DKIM_NA & FROM_NON_RO_TLD & (RO_PHISH_SUBJECT | BRAND_SUBJECT_MATCH)";
    score = 4.0;
    description = "Foreign TLD sender + RO phishing subject pattern + no DKIM";
}

DMARC_QUARANTINE_SPF_ONLY {
    expression = "DMARC_POLICY_ALLOW & R_DKIM_NA & R_SPF_ALLOW";
    score = 1.0;
    description = "DMARC passes only via SPF (no DKIM signature)";
}

AUTH_CLIENT_CORRESPONDENT_BONUS {
    expression = "APPROVED_CLIENT_CORRESPONDENT & (DMARC_POLICY_ALLOW | R_DKIM_ALLOW) & !HAS_LIST_UNSUB & !PRECEDENCE_BULK & !MAILLIST & !BOUNCE";
    score = -1.5;
    description = "Bounded bonus for authenticated exact business correspondence; never a bypass";
}

BULK_MARKETING_MULTI_SIGNAL {
    expression = "HAS_LIST_UNSUB & (PRECEDENCE_BULK | MAILLIST | MANY_INVISIBLE_PARTS | ZERO_FONT | FORGED_SENDER)";
    score = 5.0;
    description = "Newsletter/list mail with independent bulk or campaign evidence";
}

FOREIGN_MAIL_RO_CONTENT {
    expression = "FROM_NON_RO_TLD & R_MIXED_CHARSET & R_DKIM_NA";
    score = 2.0;
    description = "Foreign TLD + mixed charset + no DKIM (RO content from foreign server)";
}
CEOF

# Ensure neural + other Redis-aware modules find redis (BUGFIX: empty redis.conf
# caused neural module to silently disable, losing ~1.5 months of training.)
cat > /etc/rspamd/local.d/redis.conf << 'EOF'
servers = "127.0.0.1";
EOF

# DMARC module: rspamd 4.x requires the reporting{} block syntax
# (the 3.x `reporting = false;` boolean breaks plugin init on 4.x).
cat > /etc/rspamd/local.d/dmarc.conf << 'EOF'
reporting {
  enabled = false;
}
actions = {
  quarantine = "add_header";
  reject = "reject";
}
EOF

# Local AI/identity policy is provisioned by the edition hook below.

# Authentication proves sender identity, not that the message is wanted. The
# upstream whitelist symbols are therefore informational at GESEIDL, while
# failures remain bounded corroborating evidence rather than a solo decision.
sed -i '/# geseidl-auth-score-policy-begin/,/# geseidl-auth-score-policy-end/d' /etc/rspamd/local.d/groups.conf
cat >> /etc/rspamd/local.d/groups.conf << 'EOF'

# geseidl-auth-score-policy-begin
group "Geseidl authentication policy" {
  symbols = {
    "HAS_LIST_UNSUB" { weight = 7.5; }
    "WHITELIST_DMARC" { weight = 0.0; }
    "WHITELIST_SPF_DKIM" { weight = 0.0; }
    "WHITELIST_SPF" { weight = 0.0; }
    "WHITELIST_DKIM" { weight = 0.0; }
    "DMARC_POLICY_REJECT" { weight = 2.0; }
    "DMARC_POLICY_QUARANTINE" { weight = 1.5; }
    "R_SPF_FAIL" { weight = 1.0; }
    "R_DKIM_REJECT" { weight = 1.0; }
    "REPLYTO_EQ_TO_ADDR" { weight = 1.0; }
  }
}
# geseidl-auth-score-policy-end
EOF

# LOCAL_OUTBOUND is derived from authenticated/local SMTP provenance, not from
# From/Subject text. It is a bounded reputation signal only: all content,
# malware and attachment checks remain active and can readily outweigh it.
if ! grep -q 'geseidl-bounded-local-provenance' /etc/rspamd/local.d/groups.conf 2>/dev/null; then
	cat >> /etc/rspamd/local.d/groups.conf << 'EOF'

# geseidl-bounded-local-provenance
group "Geseidl provenance" {
  symbols = {
    "LOCAL_OUTBOUND" {
      weight = -2.0;
      description = "Bounded trust for authenticated/local SMTP provenance";
    }
  }
}
EOF
fi

# === DOVECOT IMAPSIEVE ===

# Add imap_sieve to 20-imap.conf (idempotent � only if not already present).
# Do NOT use a separate protocol imap {} block in 90-imapsieve.conf because
# Dovecot's last protocol block wins and would override 20-imap.conf plugins.
if ! grep -q 'imap_sieve' /etc/dovecot/conf.d/20-imap.conf 2>/dev/null; then
	sed -i 's/\(mail_plugins = .*imap_quota\)/\1 imap_sieve/' /etc/dovecot/conf.d/20-imap.conf
fi

cat > /etc/dovecot/conf.d/90-imapsieve.conf << 'EOF'
plugin {
  sieve_plugins = sieve_imapsieve sieve_extprograms
  sieve_global_extensions = +vnd.dovecot.pipe +vnd.dovecot.environment

  # Learn SPAM when user moves into Spam OR Junk (users frequently have both)
  imapsieve_mailbox1_name = Spam
  imapsieve_mailbox1_causes = COPY APPEND
  imapsieve_mailbox1_before = file:/etc/dovecot/sieve/learn-spam.sieve

  imapsieve_mailbox3_name = Junk
  imapsieve_mailbox3_causes = COPY APPEND
  imapsieve_mailbox3_before = file:/etc/dovecot/sieve/learn-spam.sieve

  # Learn HAM when user moves out of Spam or Junk (not to Trash)
  imapsieve_mailbox2_name = *
  imapsieve_mailbox2_from = Spam
  imapsieve_mailbox2_causes = COPY
  imapsieve_mailbox2_before = file:/etc/dovecot/sieve/learn-ham.sieve

  imapsieve_mailbox4_name = *
  imapsieve_mailbox4_from = Junk
  imapsieve_mailbox4_causes = COPY
  imapsieve_mailbox4_before = file:/etc/dovecot/sieve/learn-ham.sieve

  sieve_pipe_bin_dir = /etc/dovecot/sieve
}
EOF

# Set correct ownership on 90-imapsieve.conf (rspamd.sh runs after mail-dovecot.sh chown)
chown mail:dovecot /etc/dovecot/conf.d/90-imapsieve.conf
chmod 640 /etc/dovecot/conf.d/90-imapsieve.conf

mkdir -p /etc/dovecot/sieve
# Writable so Dovecot can compile .svbin at runtime.
chown mail:dovecot /etc/dovecot/sieve
chmod 775 /etc/dovecot/sieve

# Override ProtectSystem=full to allow writing compiled sieve binaries.
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

# Learn script
cat > /etc/dovecot/sieve/rspamd-learn.sh << 'LEARNEOF'
#!/bin/bash
exec /usr/bin/rspamc learn_"$1"
LEARNEOF
chmod +x /etc/dovecot/sieve/rspamd-learn.sh


# === CLEANUP SPAMASSASSIN ARTIFACTS ===
sed -i 's/ antispam//' /etc/dovecot/conf.d/20-imap.conf 2>/dev/null
sed -i 's/ antispam//' /etc/dovecot/conf.d/20-pop3.conf 2>/dev/null
rm -f /etc/dovecot/conf.d/99-local-spampd.conf

# === DISABLE SPAMASSASSIN ===

systemctl stop spampd 2>/dev/null
systemctl disable spampd 2>/dev/null
systemctl stop spamassassin 2>/dev/null
systemctl disable spamassassin 2>/dev/null

# === INITIAL BAYES TRAINING ===
# GESEIDL SOVEREIGN FORK: run-once + non-fatal. rspamc exits non-zero on "all learn
# conditions denied" (already-balanced classifier) and `head -z` closes the pipe early
# (SIGPIPE on find); with `set -o pipefail` (functions.sh) that aborted the ENTIRE setup
# mid-run. Guard with a marker so re-runs skip the slow 5000-file scan, and wrap each
# pipeline in `( ... ) || true` so training never stops setup. Ongoing learning is handled
# by the explicit IMAPSieve learn hooks.
RSPAMD_TRAIN_MARKER="$STORAGE_ROOT/mail/.rspamd-bayes-trained"
if [ -d "$STORAGE_ROOT/mail/mailboxes" ] && [ ! -f "$RSPAMD_TRAIN_MARKER" ]; then
	echo "Training rspamd Bayes from existing mailboxes (one-time)..."
	# Exclude every Spam/Junk Maildir from the ham pass. The former broad
	# */cur/* match also selected .Spam/cur and deterministically poisoned Bayes
	# by learning the same spam as ham immediately before learn_spam.
	( find "$STORAGE_ROOT/mail/mailboxes" -path "*/cur/*" -type f \
		! -path "*/.Spam/cur/*" ! -path "*/.Junk/cur/*" -print0 2>/dev/null | \
		head -z -n 5000 | xargs -0 -P4 -I{} rspamc learn_ham {} 2>/dev/null ) || true
	( find "$STORAGE_ROOT/mail/mailboxes" -path "*/.Spam/cur/*" -type f -print0 2>/dev/null | \
		head -z -n 5000 | xargs -0 -P4 -I{} rspamc learn_spam {} 2>/dev/null ) || true
	touch "$RSPAMD_TRAIN_MARKER"
	echo "Bayes training complete."
fi

# >>> GESEIDL EDITION OVERLAY >>>
python3 setup/geseidl_edition/zones/spam/antispam.py --apply --no-reload
# <<< GESEIDL EDITION OVERLAY <<<

# === START SERVICES ===

restart_service redis-server
restart_service rspamd
restart_service dovecot
