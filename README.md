# Mail-in-a-Box — Geseidl Edition

> **This is a fork of [mail-in-a-box/mailinabox](https://github.com/mail-in-a-box/mailinabox)** with production-tested enhancements maintained by [Geseidl IT Solutions](https://geseidl.ro/servicii-it). It is **not** the upstream project. For the official one-click MiaB setup guide, see [mailinabox.email](https://mailinabox.email).

<a href="https://geseidl.ro/servicii-it"><img src="https://geseidl.ro/assets/icons/logo-green.png" alt="Geseidl Consulting Group" height="60"></a>

## What this fork is

A **continuously-used production fork** of MiaB. Not theoretical, not a sandbox: this codebase runs the live mail server of [Geseidl Consulting Group](https://geseidl.ro) every day.

Production scale (as of April 2026):
- **70+ active mailboxes**
- **Multiple hosted domains** (one primary + several with always-BCC-archive forwards)
- **400+ GB of user-data** (mailboxes + Nextcloud + DKIM + SSL state)
- **Ubuntu 24.04 LTS + kernel 6.8** (in-place upgrade from 22.04, validated 2026-04-30)
- **1M+ message email archive** (FTS5 indexed) for retention/audit purposes
- **3+ years operational history** with iterative improvements committed back here

Every change in this fork was developed because we needed it in production. If you adopt this fork, you are running essentially the same code we run for our own business email.

---

## Why we forked

Mail-in-a-Box upstream is excellent for what it sets out to be: a one-click, opinionated mail server appliance. But "one-click" deliberately limits what you can customise. We needed three things upstream wouldn't add (and rightly so — it's not their goal):

1. **A modern spam filter (rspamd)** to replace SpamAssassin, with neural network training, brand-impersonation detection tuned for the Romanian market, and Bayes auto-retraining from the user's Trash folder.
2. **Operational reality fixes** — running MiaB behind NAT, with external DNS managed elsewhere, with a dedicated mail-archive account that BCCs all traffic.
3. **Long-lived OS support** — clean in-place upgrades when Ubuntu LTS ages out, without rebuilding the VM from scratch.

We maintain everything in branches so we can rebase onto upstream releases (currently aligned with **v75**, April 2026). When upstream ships, we follow within days.

---

## What you get on top of upstream MiaB

### 🛡️ Modern spam filtering — rspamd (with admin panel UI)

A complete alternative to SpamAssassin. Toggle from the MiaB admin panel:

- **`setup/rspamd.sh`** — full installer (~450 lines, Ubuntu-aware)
- **Neural network** module configured + trained — ML-based spam classification on top of rule-based scoring
- **Brand impersonation framework** — detects spoofs of common Romanian and international targets (banks, couriers, ANAF, tech vendors)
- **Foreign-origin RO phishing composites** — multi-signal rules for Romanian-language phishing from non-RO infrastructure
- **IMAPSieve Trash → Bayes auto-retrain** — when a user moves a message to Trash/Junk, dovecot's IMAPSieve pipeline auto-feeds it to rspamd's Bayes classifier. Continuous learning at zero admin effort.
- **`force_actions` DMARC override** for Gmail forwards — Gmail rewrites the From header on forwarded mail, breaking DMARC alignment. We override to allow it through instead of bouncing legitimate forwarded mail.
- **`spamd` and `spamassassin.sh`** kept as a reverse migration path — toggle back if rspamd misbehaves for your environment.
- **System Spam UI** — `management/templates/system-spam.html` adds an admin panel page for spam-filter status, Bayes statistics, and manual learn actions.

Branch: `feature/rspamd-spam-filter` (now superseded by `main` which rebases onto v75 + carries the rspamd integration on top).

### 🔧 Operational fixes

Several smaller fixes that came out of running MiaB long-term:

| Branch | What it does |
|---|---|
| `feature/nat-aware-checks` | Status checks that don't fail on systems behind NAT (real public IP differs from local IP) |
| `feature/external-dns-settings` | Allow external DNS providers (Cloudflare, etc.) instead of MiaB's bundled nsd |
| `feature/email-archive-option` | Always-BCC-archive setup (`archive@yourdomain.tld` receives copies of all traffic for audit/legal retention) |
| `feature/imapsieve-trash-fix` | Reliable Bayes retrain trigger when users delete spam |
| `feature/whitelist-management` | Per-user whitelist UI in admin panel |
| `feature/spamhaus-forwarders-fix` / `fix/spamhaus-dns-forwarders` | Stable DNS resolver behaviour for Spamhaus DNSBL when using external forwarders |
| `feature/rspamd-hardening` | Hardened rspamd config (rate-limits, weighted scores, custom `forbidden_file_extensions.map`) |

### 🔐 In-place security upgrades — the headline contribution

Ubuntu 22.04 LTS reaches end of standard support in April 2027. The MiaB upstream answer to "how do I upgrade?" is, fundamentally: *rebuild the VM from scratch and restore /home/user-data*. That is reasonable advice for a one-click appliance — but for organisations with a real production server, real users, and real downtime concerns, it is not always practical.

**On 2026-04-30 we successfully performed an in-place upgrade** of our production mail server from Ubuntu 22.04 to **Ubuntu 24.04 LTS** with **only 1h12min downtime** — no rebuild, no DNS changes, no mailbox migration. The upgrade pulled in:

- **Linux kernel 6.8** (vs 5.15) — much newer security patches, including CVE-2026-31431 "Copy Fail" mitigation
- **PHP 8.3** (vs 8.0)
- **Python 3.12** (vs 3.10)
- **Updated Hyper-V Linux Integration Services** (relevant if you run on Hyper-V)
- All other Ubuntu 24.04 base improvements

We documented every step, every issue we hit, every fix we applied. We also wrote scripts that automate the safe parts:

- 📖 **Full step-by-step guide**: [`UPGRADE_22.04_TO_24.04_GUIDE.md`](UPGRADE_22.04_TO_24.04_GUIDE.md) — prerequisites, snapshot, do-release-upgrade, MiaB venv rebuild, verification, rollback.
- 📋 **Plan template**: [`UPGRADE_PLAN_TEMPLATE.md`](UPGRADE_PLAN_TEMPLATE.md) — copy + fill in your environment to plan your own migration (scope, inventory, risks, decision gates, rollback runbook, verification checklist). Keep your filled version private (it will contain your hostnames/IPs/domains).
- 🛠️ **`setup-helpers/backup-mail-configs.sh`** — single-command tarball of every critical config + DKIM key + Bayes DB before you start.
- 🛠️ **`setup-helpers/upgrade-2204-to-2404.sh`** — phased automation (`--phase prep|os|miab|verify|all`) with confirmation gates.

> ⚠️ **The MiaB upstream `setup/preflight.sh` strictly rejects Ubuntu 24.04.** Running `setup/start.sh` after the OS upgrade WILL abort. Our guide explains exactly what to do instead (manually rebuild the Python venv + reinstall the embedded pip dependencies). Every problem we hit (UFW LIMIT bans, fail2ban whitelist resets, stale Python venv, missing `requirements.txt`, the `cryptography==37.0.2` pin failing on Python 3.12, `php8.0-fpm` vs `php8.3-fpm` confusion, user-data UID change) is covered.
>
> ⚠️ **VM-level backup + console access are mandatory** before you start. This is reversible only if you can roll back to a snapshot.

**Validated production deployment**:
- Date: 2026-04-30
- Downtime: 1h12min (sub 2h timebox)
- Users impacted: 70+, no mail loss
- Stable tag for this upgrade: **`geseidl-v75-2204to2404-validated`**

---

## Branches and tags

| Branch / Tag | Purpose |
|---|---|
| `main` | **Default branch. Production-deploy.** v75 + rspamd + all Geseidl fixes. Use this. |
| `upstream-mirror` | Sync of `mail-in-a-box/mailinabox` upstream `main` (currently v75). Used as rebase reference when upstream ships new releases. |
| `geseidl-v75-2204to2404-validated` (tag) | Snapshot of the exact code that survived our 22.04 → 24.04 upgrade |
| `geseidl-v75-2026-04-30` (tag) | Snapshot of the rebased-on-v75 baseline pre-upgrade |
| `feature/rspamd-spam-filter` | Original rspamd integration branch (v74-base, kept for history) |
| `feature/*`, `fix/*` | Individual feature/fix branches (most folded into `main`) |
| `backup/mail02-pre-upgrade-2026-04-30` | Manifest + SHA256 of the production config tarball pre-upgrade (tarball NOT in git — contains private keys) |

If you want to track us, watch this repo and follow `main` (default). It rebases onto upstream tags as they ship.

---

## Quick start: deploy this fork on a fresh Ubuntu 22.04 server

For a fresh install, the upstream MiaB process applies — just clone this fork instead:

```bash
git clone https://github.com/robertpopa22/mailinabox.git
cd mailinabox
git checkout main
sudo setup/start.sh
```

For an existing MiaB v74-base server who wants the rspamd features without OS changes:

```bash
cd /root/mailinabox
git remote add geseidl https://github.com/robertpopa22/mailinabox.git
git fetch geseidl
git checkout main
sudo setup/start.sh    # idempotent; will install rspamd
```

For an existing MiaB on Ubuntu 22.04 who wants to upgrade to 24.04 LTS, **read [`UPGRADE_22.04_TO_24.04_GUIDE.md`](UPGRADE_22.04_TO_24.04_GUIDE.md) first.**

---

## Maintenance commitment

This fork is maintained by Robert Popa and the Geseidl IT Solutions team. We:

- **Rebase onto upstream tags within a week** of upstream stable releases
- **Test in our own production** before tagging any branch as stable
- **Backport security fixes** from upstream as they land
- **Open issues against this fork** for problems you encounter — we read them
- **Accept pull requests** if they improve the fork without diverging from our production needs

We do **not**:

- Provide free email support (post issues on this repo or on the [upstream forum](https://discourse.mailinabox.email/))
- Promise feature parity with upstream's release cadence — we follow, we don't lead
- Maintain fork-only documentation in multiple languages — English only, except for `UPGRADE_PLAN_*.md` files which are operational notes for our team

---

## Contributing

Pull requests are welcome, especially:

- Tests of the 22.04 → 24.04 upgrade procedure on hypervisors other than Hyper-V (VMware, KVM, Proxmox, bare-metal). Open an issue with your result whether it succeeds or fails.
- Tests of rspamd on configurations other than Romanian-context (different sender locales, different DMARC policies). Help us learn where the brand-impersonation rules need adjustment.
- Bug fixes that don't add complexity for the maintenance burden.

Avoid:

- Features unrelated to operating an actual production mail server
- Things that would require us to maintain divergent code paths long-term

---

## Acknowledgements

- **[Joshua Tauberer (@JoshData)](https://github.com/JoshData)** and the upstream contributors for creating and maintaining Mail-in-a-Box. None of this fork would exist without them. The fork's purpose is to extend, not replace, their work.
- The **rspamd** team ([rspamd.com](https://rspamd.com)) for an excellent modern spam filter.
- The **Mail-in-a-Box community forum** ([discourse.mailinabox.email](https://discourse.mailinabox.email/)) where many of the integration ideas in this fork were first discussed.

---

## Maintained by

[Geseidl IT Solutions](https://geseidl.ro/servicii-it), part of [Geseidl Consulting Group](https://geseidl.ro). We are a consulting group based in Bucharest, Romania. This fork exists because we needed it for ourselves; we publish it because someone else might too.

Contact: open an issue on this repo. For commercial support of MiaB deployments based on this fork, [Geseidl IT Solutions](https://geseidl.ro/servicii-it) offers paid engagements.

---

# Mail-in-a-Box (upstream README, for reference)

By [@JoshData](https://github.com/JoshData) and [contributors](https://github.com/mail-in-a-box/mailinabox/graphs/contributors).

Mail-in-a-Box helps individuals take back control of their email by defining a one-click, easy-to-deploy SMTP+everything else server: a mail server in a box.

**Please see [https://mailinabox.email](https://mailinabox.email) for the project's website and setup guide!**

* * *

Our goals are to:

* Make deploying a good mail server easy.
* Promote [decentralization](http://redecentralize.org/), innovation, and privacy on the web.
* Have automated, auditable, and [idempotent](https://web.archive.org/web/20190518072631/https://sharknet.us/2014/02/01/automated-configuration-management-challenges-with-idempotency/) configuration.
* **Not** make a totally unhackable, NSA-proof server.
* **Not** make something customizable by power users.

Additionally, this project has a [Code of Conduct](CODE_OF_CONDUCT.md), which supersedes the goals above. Please review it when joining our community.


In The Box
----------

Mail-in-a-Box turns a fresh Ubuntu 22.04 LTS 64-bit machine into a working mail server by installing and configuring various components.

It is a one-click email appliance. There are no user-configurable setup options. It "just works."

The components installed are:

* SMTP ([postfix](http://www.postfix.org/)), IMAP ([Dovecot](http://dovecot.org/)), CardDAV/CalDAV ([Nextcloud](https://nextcloud.com/)), and Exchange ActiveSync ([z-push](http://z-push.org/)) servers
* Webmail ([Roundcube](http://roundcube.net/)), mail filter rules (thanks to Roundcube and Dovecot), and email client autoconfig settings (served by [nginx](http://nginx.org/))
* Spam filtering ([spamassassin](https://spamassassin.apache.org/)) and greylisting ([postgrey](http://postgrey.schweikert.ch/))
* DNS ([nsd4](https://www.nlnetlabs.nl/projects/nsd/)) with [SPF](https://en.wikipedia.org/wiki/Sender_Policy_Framework), DKIM ([OpenDKIM](http://www.opendkim.org/)), [DMARC](https://en.wikipedia.org/wiki/DMARC), [DNSSEC](https://en.wikipedia.org/wiki/DNSSEC), [DANE TLSA](https://en.wikipedia.org/wiki/DNS-based_Authentication_of_Named_Entities), [MTA-STS](https://tools.ietf.org/html/rfc8461), and [SSHFP](https://tools.ietf.org/html/rfc4255) policy records automatically set
* TLS certificates are automatically provisioned using [Let's Encrypt](https://letsencrypt.org/) for protecting https and all of the other services on the box
* Backups ([duplicity](http://duplicity.nongnu.org/)), firewall ([ufw](https://launchpad.net/ufw)), intrusion protection ([fail2ban](http://www.fail2ban.org/wiki/index.php/Main_Page)), and basic system monitoring ([munin](http://munin-monitoring.org/))

It also includes system management tools:

* Comprehensive health monitoring that checks each day that services are running, ports are open, TLS certificates are valid, and DNS records are correct
* A control panel for adding/removing mail users, aliases, custom DNS records, configuring backups, etc.
* An API for all of the actions on the control panel

Internationalized domain names are supported and configured easily (but SMTPUTF8 is not supported, unfortunately).

It also supports static website hosting since the box is serving HTTPS anyway. (To serve a website for your domains elsewhere, just add a custom DNS "A" record in you Mail-in-a-Box's control panel to point domains to another server.)

For more information on how Mail-in-a-Box handles your privacy, see the [security details page](security.md).


Installation
------------

See the [setup guide](https://mailinabox.email/guide.html) for detailed, user-friendly instructions.

For experts, start with a completely fresh (really, I mean it) Ubuntu 22.04 LTS 64-bit machine. On the machine...

Clone this repository and checkout the tag corresponding to the most recent release (which you can find in the tags or releases lists on GitHub):

	$ git clone https://github.com/mail-in-a-box/mailinabox
	$ cd mailinabox
	$ git checkout TAGNAME

Begin the installation.

	$ sudo setup/start.sh

The installation will install, uninstall, and configure packages to turn the machine into a working, good mail server.

For help, DO NOT contact Josh directly --- I don't do tech support by email or tweet (no exceptions).

Post your question on the [discussion forum](https://discourse.mailinabox.email/) instead, where maintainers and Mail-in-a-Box users may be able to help you.

Note that while we want everything to "just work," we can't control the rest of the Internet. Other mail services might block or spam-filter email sent from your Mail-in-a-Box.
This is a challenge faced by everyone who runs their own mail server, with or without Mail-in-a-Box. See our discussion forum for tips about that.


Contributing and Development
----------------------------

Mail-in-a-Box is an open source project. Your contributions and pull requests are welcome. See [CONTRIBUTING](CONTRIBUTING.md) to get started.


The Acknowledgements
--------------------

This project was inspired in part by the ["NSA-proof your email in 2 hours"](http://sealedabstract.com/code/nsa-proof-your-e-mail-in-2-hours/) blog post by Drew Crawford, [Sovereign](https://github.com/sovereign/sovereign) by Alex Payne, and conversations with <a href="https://twitter.com/shevski" target="_blank">@shevski</a>, <a href="https://github.com/konklone" target="_blank">@konklone</a>, and <a href="https://github.com/gregelin" target="_blank">@GregElin</a>.

Mail-in-a-Box is similar to [iRedMail](http://www.iredmail.org/) and [Modoboa](https://github.com/tonioo/modoboa).


The History
-----------

* In 2007 I wrote a relatively popular Mozilla Thunderbird extension that added client-side SPF and DKIM checks to mail to warn users about possible phishing: [add-on page](https://addons.mozilla.org/en-us/thunderbird/addon/sender-verification-anti-phish/), [source](https://github.com/JoshData/thunderbird-spf).
* In August 2013 I began Mail-in-a-Box by combining my own mail server configuration with the setup in ["NSA-proof your email in 2 hours"](http://sealedabstract.com/code/nsa-proof-your-e-mail-in-2-hours/) and making the setup steps reproducible with bash scripts.
* Mail-in-a-Box was a semifinalist in the 2014 [Knight News Challenge](https://www.newschallenge.org/challenge/2014/submissions/mail-in-a-box), but it was not selected as a winner.
* Mail-in-a-Box hit the front page of Hacker News in [April](https://news.ycombinator.com/item?id=7634514) 2014, [September](https://news.ycombinator.com/item?id=8276171) 2014, [May](https://news.ycombinator.com/item?id=9624267) 2015, and [November](https://news.ycombinator.com/item?id=13050500) 2016.
* FastCompany mentioned Mail-in-a-Box a [roundup of privacy projects](http://www.fastcompany.com/3047645/your-own-private-cloud) on June 26, 2015.

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
