#!/usr/bin/env python3
"""Comprehensive rspamd monitoring report.
Recipient, sender and authorized mailbox list come from the private site profile.
Deployed 2026-03-06 as part of IMAPSieve fix verification.
Updated 2026-03-06 v2: comprehensive report (Bayes, neural, Redis, mail volumes, actions).
"""
import json
import os
import subprocess
import smtplib
import sys
import re
import html
from email.message import EmailMessage
from datetime import datetime, timedelta
from pathlib import Path

STATE_FILE = "/var/lib/rspamd_report_state.json"
PROFILE = Path(os.environ.get('GESEIDL_ANTISPAM_PROFILE','/etc/mailinabox-geseidl-antispam.json'))
SITE = json.loads(PROFILE.read_text()).get('report',{}) if PROFILE.exists() else {}
REPORT_TO = SITE.get('to')
REPORT_FROM = SITE.get('from')
MAIL_USERS = SITE.get('mailboxes',[])
if not isinstance(MAIL_USERS,list) or any(not isinstance(user,str) or not re.fullmatch(r'[a-zA-Z0-9_.+%-]+@[a-zA-Z0-9.-]+',user) for user in MAIL_USERS):
    raise ValueError('Invalid report mailbox binding')
MAIL_FOLDERS = ["INBOX", "Spam", "Trash", "Archive", "Sent"]


def run(cmd, timeout=30):
    """Run a shell command and return stdout."""
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def run_result(cmd, timeout=30):
    """Run a command and retain whether the evidence collector succeeded."""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return result.returncode, result.stdout.strip()
    except Exception:
        return None, ""


def get_rspamc_stat():
    """Parse rspamc stat output into a dict."""
    code, raw = run_result("rspamc stat")
    stats = {"raw": raw}
    for line in raw.split("\n"):
        # Messages scanned/learned
        if "Messages scanned" in line:
            m = re.search(r"(\d+)", line.split(":")[1])
            if m:
                stats["scanned"] = int(m.group(1))
        if "Messages learned" in line and ":" in line:
            m = re.search(r"(\d+)", line.split(":")[1])
            if m:
                stats["learned"] = int(m.group(1))
        # Actions
        for action in ["reject", "soft reject", "rewrite subject", "add header", "greylist", "no action"]:
            if f"action {action}" in line:
                m = re.search(r"(\d+),\s*([\d.]+)%", line)
                if m:
                    stats[f"action_{action.replace(' ', '_')}"] = int(m.group(1))
                    stats[f"action_{action.replace(' ', '_')}_pct"] = m.group(2)
        # Treated
        if "treated as spam" in line:
            m = re.search(r"(\d+)", line)
            if m:
                stats["treated_spam"] = int(m.group(1))
        if "treated as ham" in line:
            m = re.search(r"(\d+)", line)
            if m:
                stats["treated_ham"] = int(m.group(1))
        # Bayes statfiles
        if "BAYES_SPAM" in line and "learned" in line:
            m = re.search(r"learned:\s*(\d+)", line)
            if m:
                stats["bayes_spam"] = int(m.group(1))
        if "BAYES_HAM" in line and "learned" in line:
            m = re.search(r"learned:\s*(\d+)", line)
            if m:
                stats["bayes_ham"] = int(m.group(1))
        # Total learns
        if "Total learns" in line:
            m = re.search(r"(\d+)", line.split(":")[1])
            if m:
                stats["total_learns"] = int(m.group(1))
        # Fuzzy
        if "Fuzzy hashes stored" in line:
            m = re.search(r"(\d+)", line.split(":")[1])
            if m:
                stats["fuzzy_hashes"] = int(m.group(1))
    stats["available"] = code == 0 and all(
        key in stats for key in ("scanned", "learned", "bayes_spam", "bayes_ham"))
    return stats


def get_redis_info():
    """Get Redis memory and key stats."""
    info = {}
    code, mem_raw = run_result("redis-cli info memory")
    for line in mem_raw.split("\n"):
        if ":" in line:
            k, v = line.split(":", 1)
            k = k.strip()
            v = v.strip()
            if k in ("used_memory_human", "used_memory_peak_human", "maxmemory_human", "mem_fragmentation_ratio"):
                info[k] = v
    # Key counts
    for field, pattern in (("rs_keys", "RS*"), ("neural_keys", "rn_*")):
        scan_code, keys = run_result(f"redis-cli --scan --count 1000 --pattern '{pattern}' 2>/dev/null", timeout=180)
        info[field] = len(keys.splitlines()) if scan_code == 0 else None
    # Config
    maxmem_raw = run("redis-cli config get maxmemory")
    lines = maxmem_raw.split("\n")
    if len(lines) >= 2:
        info["maxmemory_bytes"] = lines[1].strip()
    policy_raw = run("redis-cli config get maxmemory-policy")
    lines = policy_raw.split("\n")
    if len(lines) >= 2:
        info["policy"] = lines[1].strip()
    info["available"] = code == 0 and "used_memory_human" in info and "policy" in info and all(
        info.get(key) is not None for key in ("rs_keys", "neural_keys"))
    return info


def get_neural_status(redis=None):
    """Report the effective neural configuration and stored model state."""
    neural = {}
    # configdump resolves includes, defaults and overrides. Reading one local
    # fragment can disagree with what rspamd actually loaded.
    conf = run("timeout 15 rspamadm configdump neural 2>/dev/null")
    enabled_match = re.search(r"(?m)^enabled\s*=\s*(true|false)\s*;", conf)
    neural["enabled"] = enabled_match.group(1) == "true" if enabled_match else None
    neural["config_source"] = "rspamadm configdump neural" if enabled_match else "indisponibil"
    # Check counters
    counters = run("rspamc counters 2>/dev/null")
    neural_symbols = []
    for line in counters.split("\n"):
        if "NEURAL" in line:
            neural_symbols.append(line.strip())
    neural["symbols"] = neural_symbols
    # Check Redis keys (real neural prefix is rn_*, NOT *neural*)
    if redis is None:
        code, keys = run_result("redis-cli --scan --pattern 'rn_*' 2>/dev/null")
        neural["key_count"] = len(keys.splitlines()) if code == 0 else None
    else:
        neural["key_count"] = redis.get("neural_keys")
    # Redis proves only that model/vector keys exist. It does not prove the
    # effective module is enabled or that the stored model is currently used.
    neural["model_stored"] = (neural["key_count"] > 0 if neural["key_count"] is not None else None)
    return neural


def assess_health(d_learned, d_scanned, previous_learned, previous_scanned,
                  milter_ok, service_states, learn_failures=0,
                  inbound_received=None, counter_reset=False, collectors_ok=True):
    """Classify only evidence of failure; no training activity is informational."""
    status = "OK"
    alerts = []
    notes = []
    if not collectors_ok:
        status = "ALERT"
        notes.append("Statistici Rspamd/Redis indisponibile sau incomplete; valorile lipsa nu sunt zero")
    if counter_reset:
        notes.append("Restart Rspamd confirmat; contoarele de proces se compara de la noul start, nu ca pierdere Redis")
    inactive = [name for name, active in service_states.items() if active is False]
    unknown_services = [name for name, active in service_states.items() if active is None]
    if inactive:
        status = "EROARE"
        alerts.append("Servicii mail inactive: " + ", ".join(sorted(inactive)))
    if unknown_services:
        if status == "OK":
            status = "ALERT"
        notes.append("Stare servicii necolectata: " + ", ".join(sorted(unknown_services)))
    if d_learned < 0 and not counter_reset:
        status = "EROARE"
        alerts.append(f"Delta learned negativ ({d_learned}) â€” posibila problema rspamd/Redis")
    elif d_learned == 0 and previous_learned > 0 and learn_failures is not None and learn_failures > 0:
        if status == "OK":
            status = "ALERT"
        alerts.append(f"Zero mesaje invatate, dar {learn_failures} incercari de invatare au esuat")

    if previous_scanned and d_scanned < 0 and not counter_reset:
        status = "EROARE"
        alerts.append(f"Contorul scanned a regresat ({d_scanned}); verificare rspamd/Redis necesara")
    elif previous_scanned and d_scanned == 0 and not counter_reset:
        if inbound_received is not None and inbound_received > 0:
            if status == "OK":
                status = "ALERT"
            notes.append(f"{inbound_received} acceptari SMTP observate, dar zero mesaje scanate; corelarea este neconcludenta")
        elif inbound_received == 0:
            notes.append("Zero mesaje scanate si zero trafic SMTP inbound observat; fara incident demonstrat")
        else:
            if status == "OK":
                status = "ALERT"
            notes.append("Zero mesaje scanate; colectorul de trafic inbound este indisponibil, stare neconcludenta")
    if learn_failures is None:
        if status == "OK":
            status = "ALERT"
        notes.append("Jurnalul de invatare nu poate fi colectat")
    if milter_ok is None:
        if status == "OK":
            status = "ALERT"
        notes.append("Configuratia milter nu poate fi colectata; scanarea nu este confirmata")
    elif milter_ok is False:
        status = "EROARE"
        alerts.append("rspamd milter (11332) LIPSESTE din postfix smtpd_milters â€” mail nescanat! "
                      "Fix: postconf -e 'smtpd_milters = inet:127.0.0.1:11332 inet:127.0.0.1:8891 inet:127.0.0.1:8893' "
                      "+ idem non_smtpd_milters + systemctl reload postfix")
    return status, alerts, notes


def get_runtime_evidence():
    """Collect bounded health and 24h failure/traffic evidence without message data."""
    services = {}
    for service in ("rspamd", "redis-server", "postfix", "postfix@-", "dovecot"):
        code, state = run_result(f"systemctl is-active {service} 2>/dev/null")
        if code == 0 and state == "active":
            services[service] = True
        elif code is not None and state:
            services[service] = False
        else:
            services[service] = None

    def journal_text(*units):
        command = ["journalctl", "--since", "24 hours ago", "--no-pager"]
        for unit in units:
            command.extend(["-u", unit])
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        except Exception:
            return None
        return result.stdout if result.returncode == 0 else None

    learn_log = journal_text("dovecot", "rspamd")
    if learn_log is None:
        learn_failures = None
    else:
        learn_failures = sum(
            1 for line in learn_log.splitlines()
            if re.search(r"learn.*(fail|error)|cannot learn", line, re.IGNORECASE)
        )

    postfix_log = journal_text("postfix", "postfix@-")
    if postfix_log is None:
        inbound_received = None
    else:
        # A cleanup message-id is stronger than a mere SMTP connection, but it
        # still cannot prove that every accepted item traversed this counter.
        inbound_received = sum(
            1 for line in postfix_log.splitlines()
            if re.search(r"postfix/cleanup\[.*\]: [A-F0-9]+: message-id=", line)
        )
    return services, learn_failures, inbound_received


def get_mail_volumes():
    """Get mail folder message counts per user."""
    volumes = {}
    for user in MAIL_USERS:
        volumes[user] = {}
        for folder in MAIL_FOLDERS:
            raw = run(f"doveadm mailbox status -u {user} messages {folder} 2>/dev/null")
            m = re.search(r"messages=(\d+)", raw)
            volumes[user][folder] = int(m.group(1)) if m else None
    return volumes


def get_learn_events(hours=24):
    """Count real learn events from rspamd.log (rspamc learn via IMAPSieve logs here,
    NOT in dovecot journal). One 'learn class stage 4096' line per learned message/class."""
    # current + rotated (.1) cover ~24h; stage 4096 = final stage, ~1 per actual learn
    raw = run("grep -h \"learn class stage 4096 has been called for class\" "
              "/var/log/rspamd/rspamd.log /var/log/rspamd/rspamd.log.1 2>/dev/null")
    spam_count = 0
    ham_count = 0
    events = []
    for line in raw.split("\n"):
        if "for class 'spam'" in line:
            spam_count += 1
        elif "for class 'ham'" in line:
            ham_count += 1
        if line.strip():
            events.append(line.strip()[:150])
    return spam_count, ham_count, events[-20:]


def check_milter_chain():
    """rspamd milter (11332) must be in postfix smtpd_milters â€” lost on 2026-06-09 v75 upgrade."""
    code, raw = run_result("postconf -h smtpd_milters 2>/dev/null")
    if code != 0:
        return None
    return bool(re.search(r"(?:^|[\s,])inet:(?:127\.0\.0\.1|localhost|\[::1\]):11332(?:$|[\s,])", raw))


def confirmed_counter_reset(previous, stat, uptime):
    """Process restart is not persistent Bayes loss. Old states lack start identity."""
    old_start = previous.get("rspamd_start")
    return bool(old_start and old_start != "?" and uptime != "?" and old_start != uptime
                and stat.get("available") and all(
                    stat[key] >= previous.get(key, stat[key])
                    for key in ("bayes_spam", "bayes_ham")) and any(
                    stat.get(key, 0) < previous.get(key, 0) for key in ("learned", "scanned")))


def get_gpt_stats(paths=None, now=None):
    """24h, final task summaries only; backend errors are not model uncertainty.

    Read current + rotated logs locally. No message content leaves this collector.
    Missing current/unreadable logs are unknown, never a fabricated healthy zero.
    """
    paths = paths or ["/var/log/rspamd/rspamd.log", "/var/log/rspamd/rspamd.log.1"]
    now = now or datetime.now()
    cutoff = now - timedelta(hours=24)
    symbols = ["GPT_SPAM", "GPT_HAM", "GPT_PHISHING", "GPT_SCAM", "GPT_MALWARE", "GPT_MARKETING", "GPT_UNCERTAIN", "GPT_BACKEND_UNAVAILABLE", "GPT_SKIPPED_DECIDED"]
    counts = dict.fromkeys(symbols, 0)
    counts.update(available=True, backend_errors=0, timeouts=0, window_hours=24,
                  current_backend_errors=0, current_timeouts=0, current_unavailable=0,
                  current_model_results=0, current_window_minutes=60,
                  last_error=None, last_model_result=None)
    seen = set()
    for index, path in enumerate(paths):
        try:
            with Path(path).open(encoding="utf-8", errors="replace") as log:
                for line in log:
                    if "GPT_" not in line and "gpt.lua:" not in line:
                        continue
                    try:
                        stamp = datetime.strptime(line[:19], "%Y-%m-%d %H:%M:%S")
                    except ValueError:
                        continue
                    if not cutoff <= stamp <= now or line in seen:
                        continue
                    seen.add(line)
                    current = stamp >= now - timedelta(hours=1)
                    if "rspamd_task_write_log:" in line:
                        for symbol in symbols:
                            if re.search(r"\b" + symbol + r"\(", line):
                                counts[symbol] += 1
                                if symbol == 'GPT_BACKEND_UNAVAILABLE':
                                    counts['last_error'] = max(counts['last_error'] or '', stamp.isoformat())
                                    if current: counts['current_unavailable'] += 1
                                elif symbol not in ('GPT_UNCERTAIN','GPT_SKIPPED_DECIDED'):
                                    counts['last_model_result'] = max(counts['last_model_result'] or '', stamp.isoformat())
                                    if current: counts['current_model_results'] += 1
                    if "gpt.lua:" in line and "request failed:" in line:
                        counts["backend_errors"] += 1
                        counts['last_error'] = max(counts['last_error'] or '', stamp.isoformat())
                        if current: counts['current_backend_errors'] += 1
                        if "timeout" in line.lower():
                            counts["timeouts"] += 1
                            if current: counts['current_timeouts'] += 1
        except FileNotFoundError:
            if index == 0:
                counts["available"] = False
        except OSError:
            counts["available"] = False
    return counts


def apply_gpt_health(status, alerts, notes, gpt):
    if not gpt["available"]:
        if status == "OK":
            status = "ALERT"
        notes.append("Jurnalul AI nu poate fi colectat complet; disponibilitatea clasificarii este necunoscuta")
    if gpt["current_backend_errors"] or gpt["current_unavailable"]:
        if status == "OK":
            status = "ALERT"
        alerts.append(f'AI degradat in ultima ora: {gpt["current_backend_errors"]} erori backend, '
                      f'{gpt["current_timeouts"]} timeouturi, {gpt["current_unavailable"]} mesaje fara rezultat de model; '
                      'GPT_UNCERTAIN nu confirma functionarea AI')
    elif gpt['backend_errors'] or gpt['GPT_BACKEND_UNAVAILABLE']:
        recovered = bool(gpt['last_model_result'] and gpt['last_error']
                         and gpt['last_model_result'] > gpt['last_error'])
        notes.append('Istoric AI 24h: '+str(gpt['backend_errors'])+' erori; ultima ora fara erori observate. '
                     + ('Rezultat real de model ulterior ultimei erori: revenire observata.' if recovered
                        else 'Revenirea nu este confirmata printr-un rezultat de model ulterior.'))
        if not recovered and status == 'OK': status = 'ALERT'
    return status


def get_rule_update_status(path='/var/lib/geseidl-antispam-updates/status.json', now=None):
    from datetime import timezone
    now = now or datetime.now(timezone.utc)
    try:
        result = json.loads(Path(path).read_text())
        age = (now - datetime.fromisoformat(result['checked_at'])).total_seconds()
        if age < -300 or age > 36 * 3600:
            result['status'] = 'STALE'
        return result
    except (OSError, ValueError, KeyError, TypeError):
        return {'status': 'UNKNOWN'}


def get_server_resources():
    """Get server RAM and disk info."""
    res = {}
    free_raw = run("free -h")
    for line in free_raw.split("\n"):
        if line.startswith("Mem:"):
            parts = line.split()
            if len(parts) >= 7:
                res["ram_total"] = parts[1]
                res["ram_used"] = parts[2]
                res["ram_available"] = parts[6]
    disk_raw = run("df -h / | tail -1")
    parts = disk_raw.split()
    if len(parts) >= 5:
        res["disk_total"] = parts[1]
        res["disk_used"] = parts[2]
        res["disk_avail"] = parts[3]
        res["disk_pct"] = parts[4]
    return res


def get_reputation_health():
    import importlib.util
    path=Path('/usr/local/lib/geseidl-antispam/reputation_dns.py')
    try:
        spec=importlib.util.spec_from_file_location('reputation_dns',path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        return module.probe()
    except Exception:
        return {'status':'UNKNOWN','probes':[]}


def get_rspamd_uptime():
    """Get rspamd process uptime."""
    raw = run("systemctl show rspamd --property=ActiveEnterTimestamp 2>/dev/null")
    return raw.replace("ActiveEnterTimestamp=", "").strip() if raw else "?"


def effective_module_status(command, module):
    code, conf = run_result(command)
    if code != 0:
        return None
    if module == "imap_sieve":
        # Dovecot 2.4 returns a setting map; 2.3 returns a space-separated list.
        found = re.search(r"(?m)^imap_sieve\s*=\s*(yes|no)\s*$", conf)
        return found.group(1) == "yes" if found else "imap_sieve" in conf.split()
    found = re.search(r"(?m)^enabled\s*=\s*(true|false)\s*;", conf)
    return found.group(1) == "true" if found else None


def availability_label(value):
    return "DA" if value is True else ("NU" if value is False else "NECUNOSCUT")


def model_label(neural):
    if neural.get("model_stored") is None:
        return "NECUNOSCUT"
    return "MODEL STOCAT" if neural["model_stored"] else "FARA MODEL STOCAT"


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def send_report(subject, body, status="WARN"):
    if not REPORT_TO or not REPORT_FROM:
        raise ValueError('Report sender and recipient are required in the private site profile')
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = REPORT_FROM
    msg["To"] = REPORT_TO
    # Alerting policy: OK is archived automatically by the recipient's sieve rule,
    # WARN/CRITICAL stay in INBOX. See NET-ADMIN/docs/ALERTING-POLICY.md.
    msg["X-Geseidl-Status"] = status
    msg["X-Geseidl-Source"] = "mail02-rspamd"
    msg.set_content(body)
    msg.add_alternative(
        '<!doctype html><html lang="ro"><body style="margin:0;background:#f4f7f5;'
        'font-family:Arial,sans-serif;color:#1f2933"><div style="max-width:820px;'
        'margin:24px auto;background:#fff;border:1px solid #d8e2dc;border-radius:10px;'
        'overflow:hidden"><div style="padding:18px 24px;background:#174f3a;color:#fff">'
        f'<h1 style="margin:0;font-size:20px">{html.escape(subject)}</h1></div>'
        '<div style="padding:24px"><pre style="white-space:pre-wrap;font:13px/1.5 '
        f'Consolas,monospace">{html.escape(body)}</pre></div></div></body></html>',
        subtype="html",
    )
    try:
        with smtplib.SMTP("127.0.0.1", 25) as smtp:
            smtp.send_message(msg)
        return True
    except Exception as e:
        print(f"Email delivery failed: {type(e).__name__}", file=sys.stderr)
        return False


def main():
    now = datetime.now()
    stat = get_rspamc_stat()
    redis = get_redis_info()
    neural = get_neural_status(redis)
    volumes = get_mail_volumes()
    spam_events, ham_events, recent = get_learn_events(24)
    gpt = get_gpt_stats()
    resources = get_server_resources()
    uptime = get_rspamd_uptime()
    imapsieve = effective_module_status("doveconf -f protocol=imap -h mail_plugins", "imap_sieve")
    gpt_enabled = effective_module_status("rspamadm configdump gpt 2>/dev/null", "gpt")
    previous = load_state()

    # Deltas
    d_spam = stat.get("bayes_spam", previous.get("bayes_spam", 0)) - previous.get("bayes_spam", 0)
    d_ham = stat.get("bayes_ham", previous.get("bayes_ham", 0)) - previous.get("bayes_ham", 0)
    # Missing statistics are never fed into negative-delta alarms as fabricated zeros.
    d_learned = stat.get("learned", previous.get("learned", 0)) - previous.get("learned", 0)
    d_scanned = stat.get("scanned", previous.get("scanned", 0)) - previous.get("scanned", 0)
    counter_reset = confirmed_counter_reset(previous, stat, uptime)
    if counter_reset:
        d_learned, d_scanned = stat["learned"], stat["scanned"]

    # Low-volume check: milter chain (postconf) is the definitive test for the
    # 2026-06-09 v75 incident; a small-but-nonzero delta with the milter present
    # is just low traffic (weekends drop well under 50 msgs/24h).
    milter_ok = check_milter_chain()
    service_states, learn_failures, inbound_received = get_runtime_evidence()
    status, alerts, notes = assess_health(
        d_learned, d_scanned,
        previous.get("learned", 0), previous.get("scanned", 0),
        milter_ok, service_states,
        learn_failures=learn_failures,
        inbound_received=inbound_received,
        counter_reset=counter_reset,
        collectors_ok=stat["available"] and redis["available"],
    )
    status = apply_gpt_health(status, alerts, notes, gpt)
    rule_update = get_rule_update_status()
    reputation = get_reputation_health()
    if reputation['status'] != 'OK':
        if status == 'OK': status = 'ALERT'
        alerts.append('Filtre reputatie DNS: '+reputation['status']+'; verificati recursia directa si gateway-ul')
    if rule_update['status'] != 'OK':
        if status == 'OK':
            status = 'ALERT'
        alerts.append('Actualizare reguli suplimentare: ' + rule_update['status'] + '; ultima versiune buna este pastrata')
    if stat["available"] and any(stat[key] < previous.get(key, stat[key])
                                  for key in ("bayes_spam", "bayes_ham")):
        status = "EROARE"
        alerts.append("Contoarele Bayes persistente au regresat; restartul nu explica pierderea datelor")

    bayes_spam = stat.get("bayes_spam", "N/A")
    bayes_ham = stat.get("bayes_ham", "N/A")
    total_bayes = bayes_spam + bayes_ham if stat["available"] else "N/A"
    ratio_spam = f"{bayes_spam * 100 / total_bayes:.1f}" if isinstance(total_bayes, int) and total_bayes else "?"
    ratio_ham = f"{bayes_ham * 100 / total_bayes:.1f}" if isinstance(total_bayes, int) and total_bayes else "?"
    delta_labels = [f"{n:+6}" if stat["available"] else "   N/A" for n in (d_spam, d_ham, d_learned, d_scanned)]

    sep = "=" * 60

    body = f"""Raport rspamd â€” {now.strftime("%Y-%m-%d %H:%M")}
{sep}
Status: {status}
rspamd uptime since: {uptime}

BAYES STATISTICS
{"-" * 40}
  BAYES_SPAM learned: {bayes_spam:>8}
  BAYES_HAM learned:  {bayes_ham:>8}
  Total learned:      {total_bayes:>8}
  Ratio spam/ham:     {ratio_spam}% / {ratio_ham}%
  Total learns (rspamc): {stat.get("total_learns", "?")}

DELTA (de la esantionul precedent; dupa restart: contoare de proces de la start)
{"-" * 40}
  Spam learned: {delta_labels[0]}
  Ham learned:  {delta_labels[1]}
  Total learned:{delta_labels[2]}
  Msgs scanned: {delta_labels[3]}

SCAN PERFORMANCE (de la deploy)
{"-" * 40}
  Total scanate:     {stat.get("scanned", "?")}
  Reject:            {stat.get("action_reject", "?"):>5}  ({stat.get("action_reject_pct", "?")}%)
  Add header (spam): {stat.get("action_add_header", "?"):>5}  ({stat.get("action_add_header_pct", "?")}%)
  Greylist:          {stat.get("action_greylist", "?"):>5}  ({stat.get("action_greylist_pct", "?")}%)
  No action (ham):   {stat.get("action_no_action", "?"):>5}  ({stat.get("action_no_action_pct", "?")}%)
  Treated as spam:   {stat.get("treated_spam", "?")}
  Treated as ham:    {stat.get("treated_ham", "?")}

NEURAL NETWORK
{"-" * 40}
  Enabled efectiv: {"DA" if neural["enabled"] is True else ("NU" if neural["enabled"] is False else "NECUNOSCUT")}
  Config source:   {neural["config_source"]}
  Redis keys: {neural["key_count"]}
  Model state: {model_label(neural)}
"""
    if neural["symbols"]:
        body += "  Symbols:\n"
        for s in neural["symbols"][:5]:
            body += f"    {s}\n"

    body += f"""
REDIS
{"-" * 40}
  Memory:      {redis.get("used_memory_human", "?")} / {redis.get("maxmemory_human", "?")}
  Peak:        {redis.get("used_memory_peak_human", "?")}
  Fragmentation: {redis.get("mem_fragmentation_ratio", "?")}
  Policy:      {redis.get("policy", "?")}
  Bayes tokens (RS* keys): {redis.get("rs_keys", "?")}
  Neural keys:             {redis.get("neural_keys", "?")}

MAIL VOLUMES (foldere)
{"-" * 40}
"""
    for user in MAIL_USERS:
        body += f"  {user}:\n"
        for folder in MAIL_FOLDERS:
            val = volumes.get(user, {}).get(folder)
            body += f"    {folder:>10}: {val if val is not None else 'N/A'}\n"

    body += f"""
SERVER RESOURCES
{"-" * 40}
  RAM:  {resources.get("ram_used", "?")} / {resources.get("ram_total", "?")} (available: {resources.get("ram_available", "?")})
  Disk: {resources.get("disk_used", "?")} / {resources.get("disk_total", "?")} ({resources.get("disk_pct", "?")})

LEARN EVENTS (fisiere curent + .1, stage 4096; fereastra variabila de rotatie)
{"-" * 40}
  learn_spam: {spam_events}
  learn_ham:  {ham_events}

FILTRU LLM (gpt module; enabled efectiv: {availability_label(gpt_enabled)})
{"-" * 40}
  Fereastra: ultimele 24h; colector complet: {availability_label(gpt["available"])}
  Ultima ora: {gpt["current_backend_errors"]} erori / {gpt["current_timeouts"]} timeouturi / {gpt["current_model_results"]} rezultate reale
  Ultima eroare: {gpt["last_error"]}; ultimul rezultat real: {gpt["last_model_result"]}
  Istoric 24h: {gpt["backend_errors"]} erori backend; {gpt["timeouts"]} timeouturi
  GPT_BACKEND_UNAVAILABLE: {gpt["GPT_BACKEND_UNAVAILABLE"]}
  GPT_SKIPPED_DECIDED: {gpt["GPT_SKIPPED_DECIDED"]}
  GPT_SPAM:      {gpt.get("GPT_SPAM", 0)}
  GPT_HAM:       {gpt.get("GPT_HAM", 0)}
  GPT_PHISHING:  {gpt.get("GPT_PHISHING", 0)}
  GPT_SCAM:      {gpt.get("GPT_SCAM", 0)}
  GPT_MALWARE:   {gpt.get("GPT_MALWARE", 0)}
  GPT_MARKETING: {gpt.get("GPT_MARKETING", 0)}
  GPT_UNCERTAIN: {gpt.get("GPT_UNCERTAIN", 0)}
  Update reguli SA: {rule_update['status']}; revizie {rule_update.get('revision', '?')}
  Ultima verificare update: {rule_update.get('checked_at', '?')}
  Reputatie DNS (canare pozitive si negative): {reputation['status']}
"""

    if alerts:
        body += f"\nALERTE\n{'-' * 40}\n"
        for a in alerts:
            body += f"  ! {a}\n"

    if notes:
        body += f"\nOBSERVATII\n{'-' * 40}\n"
        for note in notes:
            body += f"  - {note}\n"

    if recent:
        body += f"\nUltimele {len(recent)} events:\n"
        for e in recent:
            body += f"  {e}\n"

    body += f"""
{sep}
SUMAR
{sep}
  Bayes: {bayes_spam} spam + {bayes_ham} ham = {total_bayes} ({ratio_spam}%/{ratio_ham}%)
  Neural: {"activ" if neural["enabled"] is True else ("inactiv" if neural["enabled"] is False else "stare necunoscuta")}; {model_label(neural)} ({neural["key_count"]} keys rn_*)
  Redis: {redis.get("used_memory_human", "?")} / {redis.get("maxmemory_human", "?")}
  Plugin IMAPSieve incarcat: {availability_label(imapsieve)} (nu este dovada unei invatari reusite)
  Fuzzy hashes: {stat.get("fuzzy_hashes", "?")}

---
Raport generat de /usr/local/bin/rspamd_learn_report.py
"""

    subject = f"[Mail] rspamd {status} â€” {now.strftime('%Y-%m-%d')}"
    if previous.get("learned"):
        subject += f" (delta: {d_learned:+d})"

    # Send email only when there is something actionable (ALERT/EROARE) or once a
    # week as a health digest (Monday). OK days are silent â€” the daily cron still
    # runs and updates state below, so 24h deltas stay correct.
    weekly_digest = now.weekday() == 0  # Monday
    if status != "OK" or weekly_digest:
        mail_status = {"OK": "OK", "ALERT": "WARN"}.get(status, "CRITICAL")
        if not send_report(subject, body, status=mail_status):
            return 1
        print(f"Report sent: {subject}")
    else:
        print(f"Status OK â€” email skipped: {subject}")

    # Retain the last valid baseline during collection failures.
    if not stat["available"] or not redis["available"]:
        return 2 if status != "EROARE" else 1
    state = {
        "timestamp": now.isoformat(),
        "bayes_spam": stat.get("bayes_spam", 0),
        "bayes_ham": stat.get("bayes_ham", 0),
        "learned": stat.get("learned", 0),
        "scanned": stat.get("scanned", 0),
        "rspamd_start": uptime,
    }
    save_state(state)
    return {"OK": 0, "ALERT": 2, "EROARE": 1}[status]


if __name__ == "__main__":
    sys.exit(main())
