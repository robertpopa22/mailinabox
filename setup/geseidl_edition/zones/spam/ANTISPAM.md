# Antispam and reputation DNS

Edition 0.20.0. Rspamd remains the filtering engine. Reputation lookups must work
independently of AI; a blocked lookup is neither a clean result nor a spam verdict.

## Modules and policy

- `brand_guard.lua`: brand identity, sensitive account/payment request and unrelated
  sender domain combine into a +7 signal. Includes confusable letters, subject/body
  evidence, brand-specific official domains and legitimate-context exceptions.
  Authentication of an unrelated sender domain does not authenticate the claimed brand.
- AI eligibility: skip at deterministic score `max(8, add_header + 3)` inclusive;
  below that boundary retain native GPT eligibility. With add_header=5, 7.99 remains
  eligible and 8 skips. The +3 margin covers GPT_HAM's configured -2. Authenticated
  submission is excluded. `GPT_SKIPPED_DECIDED` and `GPT_BACKEND_UNAVAILABLE`
  distinguish policy decisions from backend failures.
- Local CPU defaults: AI90s, task120s, extracted input500, output72, context32768,
  reasoning disabled. No cloud fallback or automatic learning. Verify that the
  effective mail transport timeout exceeds the task budget.
- `antispam_rule_update.py`: only twelve audited account-phishing body regexes from
  signed official SA updates. Four phrase families create a candidate; local +2
  applies only without equivalent native, brand or AI phishing evidence. Native
  Rspamd continues to own overlapping authentication, reputation and URL checks.
- Daily04:15 + up to15 minutes jitter, persistent systemd timer. GPG verification,
  persistent revision high-water, strict atom allowlist, eight native canaries,
  atomic publication and last-good rollback. No arbitrary SA plugins/eval/scoring.
  Updates outside this subset require review; this is not a general SA translator.
- `rspamd_report.py`: the existing report gains backend statistics, update freshness
  (36h), and six live reputation/ordinary DNS canaries. Errors and unknown status
  remain visible. Recipients and authorized mailboxes are explicit private bindings.

## Private profile and deployment

Use `/etc/mailinabox-geseidl-antispam.json`, root-owned0600. Example placeholders:

```json
{
  "enabled": true,
  "ai": {
    "url": "http://127.0.0.1:11434/api/chat",
    "model": "local-approved-model",
    "timeout": 90,
    "task_timeout": 120,
    "max_input": 500,
    "max_output": 72,
    "context": 32768
  },
  "report": {
    "to": "operator@example.com",
    "from": "monitor@example.com",
    "mailboxes": ["operator@example.com"]
  }
}
```

Prerequisites: native Rspamd and SpamAssassin4.0.2 tools, an already GPG-verified
official bundle at `/var/lib/spamassassin/4.000002`, approved local AI endpoint,
and a configuration backup. The fixed seed directory targets this supported SA
package cohort; another package version needs explicit adaptation. Bootstrap the
subset before enabling its Rspamd import on first installation:

```sh
sudo python3 setup/geseidl_edition/zones/spam/antispam_rule_update.py --bootstrap
sudo python3 setup/geseidl_edition/zones/spam/antispam.py
sudo python3 setup/geseidl_edition/zones/spam/antispam.py --apply
```

No profile means explicit SKIP. Missing rule seed or conflicting operator policy
fails before deployment. `--root /path/to/clone` stages a copied filesystem;
validate with native `rspamadm --var=LOCAL_CONFDIR=/path/to/clone/etc/rspamd configtest`.
The setup hook replays the edition, replacing the obsolete inline20s/score4 setup.
It does not install a model, migrate a backend or create a new reporting schedule.
Backups in `/var/backups/geseidl-antispam-*` include original existence/ownership
and changed-file hashes. On failure only those files are restored automatically.
Manual recovery: stop the update timer, restore manifest-listed originals with
their ownership/modes, remove only manifest-listed newly created files, run native
configtest, daemon-reload and Rspamd reload. Preserve new mail, Bayes and queues.

## Reputation resolver

`../dns/reputation_dns.py` plans by default; `--verify` checks health and `--apply`
installs BIND recursion exceptions for `uribl.com` and `dnswl.org`. Ordinary
forwarders, Spamhaus/DQS and unrelated zones remain configured. Configtest,
targeted cache invalidation, six positive/negative/control canaries and rollback
are mandatory. DNS setup invokes this before its legacy idempotent early return.

Public/shared forwarders can be refused. Gateway interception can also defeat
correct BIND recursion. Prove direct authoritative resolution, including TCP,
before concluding a provider is down. Optional `../dns/gateway_dns.py` supports
the UniFi DNSFILTER chain. On the gateway provide a private JSON with exact
`source_ip`, `source_mac`, `interface`; default prints the plan. `--install`
requires the existing `udm-boot` mechanism. It maintains only two NAT RETURN rules
for that IP/MAC/interface on TCP/UDP53; firewall/IPS and other clients retain their
policies. No subnet exemption/ACCEPT. The watcher verifies the neighbour binding
every15s and removes its rules if identity cannot be confirmed.

Recovery: `systemctl disable --now geseidl-reputation-dns` and removal of its own
`/data/on_boot.d/20-geseidl-reputation-dns.sh` disables persistence; stopping the
service removes its exact rules. Keep private profiles and firewall backups out
of Git. BIND recovery restores only its manifest-listed files, then named-checkconf,
rndc reconfig and targeted cache invalidation.

This permits actual recursion; it does not bypass licensing, quotas or terms.
Future quota refusal remains a visible health failure requiring an appropriate
provider arrangement. [URIBL refusal policy](https://uribl.com/refused.shtml),
[URIBL test points](https://uribl.com/about.shtml),
[DNSWL query policy/test points](https://www.dnswl.org/?page_id=15).

## Acceptance evidence

2026-10-11:40 targeted Python tests,25 Lua identity cases and12 AI boundaries;
native clone configtest/idempotence, controlled rollback failures and live reload.
Six privately retained real messages: one phishing add-header without AI, five
legitimate no-action, no reputation BLOCKED symbols. Phishing acquired native
URIBL_GREY; legitimate sender IPs yielded DNSWL127.0.5.0 and native
RCVD_IN_DNSWL_NONE (trust level0 is deliberately neutral). Official synthetic
URIBL test matched BLACK/GREY/RED. Gateway firewall unchanged, only two owned NAT
rules, watcher recovery and boot-hook replay passed. Full gateway reboot was not
performed. Corpus is a regression sample, not a universal false-positive estimate.
Raw mail and private deployment details are excluded.

Broad local unit validation:111 passed,2 skipped. Legacy standalone SMTP/DNS/mail
integration scripts are excluded from pytest; run only with their explicit
deployment arguments and separate authorization for sending operations.
