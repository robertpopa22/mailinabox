# Optional publisher release channels

`nextcloud_schema_migration.py` is an explicit, clone-tested reconciliation for
seven historical Nextcloud 35.0.1 SQLite column definitions. It uses the installed
publisher's DDL, retains all application rows and existing indexes, and refuses
unknown columns, invalid JSON or IDs, foreign keys and triggers. It supports a
read-only plan; applying requires a new coherent backup and quiesced application
writers. It is not an automatic setup migration. Native schema-check findings
for disabled apps, retained historical data and postSchemaChange indexes remain
visible. Recovery must restore only metadata over current rows, never a stale DB.

This directory belongs to the Geseidl package. It does not change upstream's
default distribution package selection or require upstream to follow our release
cadence. General compatibility fixes are prepared separately for upstream.

`nsd_package.py` builds NSD4.15.2 from the publisher archive pinned by SHA256,
using an authenticated native NSD package supplied by the operator as the
integration baseline. It retains native service hardening, maintainer scripts and
conffile handling. It replaces binaries/manuals in an isolated package tree;
building does not install a package or restart any running service. Requires
Python3.12+, the native build dependencies, and `dpkg-deb`.

Before installation, test the exact package binaries with an isolated signed DNS
zone, TCP/UDP queries, negative answers, refused recursion, persisted state and
the live configuration read-only. Retain the authenticated old package and prove
recovery. Version-sensitive state formats and service sandbox restrictions must
be checked; a private build prefix passing a query is insufficient.

The recipe keeps response-rate limiting enabled by default, matching the native
Ubuntu baseline instead of adopting the publisher's disabled default. Record and
compare effective control/authentication/security defaults across package origins;
unchanged configuration bytes alone do not prove unchanged policy.

The resulting `nsd_4.15.2+geseidl3_*.deb` is a local release-channel artifact,
not an official NLnet Labs or Ubuntu package. Its manifest records source, native
baseline and artifact hashes. Artifacts and environment values remain outside
this public source repository. Future releases require refreshed pins and tests;
there is no unattended package-channel migration in this implementation.

Sources: [NSD releases](https://nlnetlabs.nl/projects/nsd/download/),
[upstream contribution ledger](../../../docs/upstream/CONTRIBUTIONS.md).

`bind_channel.py --work DIRECTORY --version 9.20.29` stages the five installed
BIND packages from ISC's stable Ubuntu 24.04 repository. It verifies the full
publisher signing-key fingerprint, the InRelease signature, the package-index
checksum and each package checksum. It refuses a different publisher version or
an incomplete package set. Staging writes only to a new private directory and
does not install packages or restart services.

For an existing Ubuntu installation, run `bind_defaults.py` before installing
the ISC packages. ISC removes Ubuntu's default-zone conffiles and replaces an
unmodified `named.conf`. The adapter copies the existing standard zone files
under edition-owned names and updates the include, so `--force-confold` preserves
the configuration. It refuses nonstandard files or conflicts; it does not change
zone data, resolver options, keys or service state. Test both the new and old
packages with these preserved files. Native package integration includes conffile
removal as well as binary/runtime compatibility.

After testing the exact binaries, native service command, effective resolver
configuration, DNSSEC positive/negative answers and old-package recovery, an
operator may use the separate `--enable-channel` option with the same directory
and reviewed version. This persists a Signed-By key and repository limited to
BIND packages; other packages from that origin have negative preference. It
refuses conflicting existing channel files. It installs no packages and leaves
APT refresh and the bounded migration to the operator. The ordinary upstream
Ubuntu channel remains unchanged unless this Geseidl option is explicitly used.

Source: [ISC-maintained BIND packages](https://kb.isc.org/docs/isc-packages-for-bind-9).

`dovecot24.py` converts a reviewed SQLite/Maildir 2.3 configuration to a 2.4
candidate, using operator-supplied private parameters. Unsupported settings fail
closed. It preserves SQL user/network restrictions, identity/path templates,
byte quotas and percentage grace, SMTP auth/LMTP endpoints, TLS, personal/global
Sieve and COPY/APPEND learning rules. It explicitly retains trusted localhost
authentication; 2.4's `ssl=required` no longer bypasses trusted networks. Legacy
long variable aliases also need conversion: a successful login with auth-policy
fallback is not evidence that the policy integration works.

The candidate uses configuration version 2.4.5. Storage defaults to 2.3.21 for
initial recovery tests; `--storage-version 2.4.5` enables the current storage
features, including the protected THREAD cache format. Before production, test
the final format and authenticated old-package recovery with messages written
by the new server. Preserve UIDVALIDITY and UIDs; never restore an old mailbox or
user database over messages that arrived after reopening.

After a separately tested migration, store its trusted profile as root:root,
0600 at `/etc/mailinabox-geseidl/dovecot24.json`, inside a root:root, 0700
directory. `dovecot24_setup.py` validates ownership, reconciles that profile with
the box's existing storage root/hostname, checks the actual 2.4 parser and writes
the main config atomically only when needed. The edition's setup branch uses this
path for an installed 2.4 server; the inherited 2.3 setup remains available.
Keep the private profile in encrypted deployment backups. It contains a policy
nonce and configuration and must never be committed to this public repository.
Package channel changes and initial migration remain explicit operator actions.

Required acceptance includes IMAP143 for trusted applications, verified IMAPS/
POP3S, wrong-password and disallowed-source rejection, SQL injection rejection,
native SMTP-auth socket, local LMTP delivery/quotas, ManageSieve CRUD, prohibited
redirect execution with local keep, spam/ham learning callbacks and working
auth-policy HTTP. Check actual policy errors, not only a successful login. Use
private network, spool, logs, runtime and state; Dovecot's instance registry also
needs isolation. Native service options that transient D-Bus units cannot set
must be tested through a copy of the actual native unit.

Sources: [Dovecot 2.4 upgrade guide](https://doc.dovecot.org/latest/installation/upgrade/2.3-to-2.4.html),
[publisher releases and signing key](https://github.com/dovecot/core/releases).

## Optional Postfix publisher packages

`postfix_package.py` builds core, SQLite and PCRE packages together from the
pinned, separately signature-verified Postfix 3.11.7 archive. It retains native
distribution units, maintainer scripts, alternatives and configuration handling;
compiled ABI and manuals use the same source. This recipe is tested for Ubuntu
24.04. It only builds; installation and recovery remain operator actions.

Test an isolated queue/network/state with native Dovecot authentication, TLS,
wrong-password/SQL-injection/refused-relay controls, LMTP, archive delivery and
the ordinary user's queue command. Extracted binaries need the same native
postdrop/postqueue initialization performed by distribution postinst.
`postfix_tls.py` keeps older releases unchanged and removes the deprecated custom
DH parameter on current versions, using publisher defaults; certificate keys and
the explicit TLS policy stay intact. The inherited setup calls this only with
the edition marker present.

The general setup maps use `proxy:sqlite` so chrooted readers access SQLite through
the native non-chroot proxymap service. WAL also has a side-file/cold-start
requirement. `maildb_journal.py --database <private-path> --migrate` is an explicit
metadata-only migration to rollback journaling, performed after coherent backup
and stopping consumers. Test the final mode with both new and old packages;
retain all records/newly queued messages. No old database/queue is restored.
This does not change the separate Roundcube or Nextcloud database modes.

Sources: [Postfix stable source](https://postfix.cs.utah.edu/source/),
[proxymap](https://www.postfix.org/proxymap.8.html),
[TLS defaults](https://www.postfix.org/DEPRECATION_README.html),
[SQLite read-only WAL](https://sqlite.org/wal.html#read_only_databases).

## Optional nginx stable channel

`nginx_channel.py` stages the official Ubuntu 24.04 stable package using the
publisher key bundle, signed InRelease and package hashes. Enable its Signed-By
channel separately only after migration and recovery acceptance; pin nginx alone,
excluding other packages from this origin. Stable is distinct from mainline.

The publisher package replaces Ubuntu nginx-common. Preserve all existing
configuration/snippets and inspect native conffile/service handling; test package
installation as well as candidate parsing. Keep authenticated old packages.
`nginx_http2.py` preserves pre-1.25.1 syntax and adapts legacy listeners on current
versions, refusing conflicting or mixed listener scope. The edition renderer
uses it before writing its generated configuration. No additional protocol or
dynamic module is activated. Test isolated native TLS/ALPN/HTTP2/FastCGI with
private runtime/log/cache/FPM session paths and verified GET/POST methods, then
old-binary recovery and nominal application access after installation.

Sources: [official package channel](https://nginx.org/en/linux_packages.html),
[HTTP/2 directive](https://nginx.org/en/docs/http/ngx_http_v2_module.html).

## Optional Redis publisher channel and recovery preparation

`redis_channel.py` stages the reviewed server/tools pair from signed publisher
metadata; enable the Ubuntu 24.04 Signed-By channel separately after acceptance.
Only those two packages receive priority 600; other packages from that origin are
excluded. The channel does not install packages or migrate data.

Before replacement, `redis_aof.py --prepare-recovery` operates on the running
loopback Redis, creates a complete plain-command AOF and waits for successful
rewrite before saving configuration. It keeps every-second fsync and the existing
RDB snapshots. Test the old binary against the new AOF with new writes retained;
this contract covers the existing core data types, not newly introduced commands
or module types. Do not switch appendonly by editing an offline config alone.
Never restore an old RDB over subsequent activity.

`redis_service.py --preserve-service` captures the reviewed distribution service
as a drop-in before changing package origin, keeping startup arguments and
hardening. Review this profile on future service changes. Keep existing Redis
configuration and listener scope. Publisher 8.10 includes the in-tree vectorset
component; external Bloom/Search/JSON/TimeSeries libraries are not loaded by this
migration. Preserve that distinction when reporting MODULE LIST.

Acceptance compares typed values and absolute expiry times on isolated copies,
using exact IEEE754 zset scores rather than their version-dependent text format.
Report short-lived exclusions explicitly. Stop SMTP and its filter together for
the bounded replacement so an unavailable filter cannot create an accept bypass;
verify real mail/application access after reopening.

Sources: [publisher APT channel](https://redis.io/docs/latest/operate/oss_and_stack/install/install-stack/apt/),
[persistence](https://redis.io/docs/latest/operate/oss_and_stack/management/persistence/),
[in-tree modules](https://github.com/redis/redis/blob/8.10.2/modules/MODULES.md).

## Optional Fail2ban publisher asset

`fail2ban_package.py` stages a specifically reviewed stable GitHub release asset,
checking its API SHA256, official HTTPS URL and exact Debian version/architecture.
This is distinct from PGP verification; no such claim is made. Release 1.1.1 uses
the corrected `upstream2` asset, whose Debian version contains `~upstream2`.
Installation, local configuration preservation and recovery remain operator steps.

Test all enabled jails, actual healthy/failed authentication logs and both allowed
and refused network connections in a private kernel firewall. Preserve the ban
database, new bans and original timestamps across old-version recovery. Keep the
current Dovecot 2.4-compatible filter when recovering an older Fail2ban binary.
Account for asynchronous restoration before comparing active bans.

Native service fixtures must use their own RuntimeDirectory/StateDirectory names
and prove the live control socket still exists and responds after cleanup. Test
socket activation through stop/restart: the 1.1.1 publisher listener showed
POLLHUP when the daemon shut down its inherited FD. The validated deployment uses
the traditional native daemon-owned control socket, with optional socket
activation disabled in both systemd and package-helper state.

Source: [Fail2ban publisher releases](https://github.com/fail2ban/fail2ban/releases).

## Optional SpamAssassin publisher cohort

`spamassassin_package.py` builds the pinned 4.0.2 source for Ubuntu 24.04 from
retained, authenticated native spamassassin/spamd/spamc/sa-compile packages.
Verify the publisher detached signature separately; the recipe verifies source
SHA256 before creating its workspace and refuses an unreviewed base. All four
packages use one source/version, keep native units/maintainers/config handling,
avoid overlapping file ownership and retain matching manuals and readable modes.
The recipe only builds, without installing packages or migrating learned data.

The release source does not bundle the full scoring rules. Stage signed updates
with the candidate executable/library cohort, including child lint commands,
and provide the reviewed `4.000002` rule directory before reopening the daemon.
Keep old rule directories available for recovery. Do not weaken GPG verification.
Source and rule-update signing fingerprints differ and are recorded separately.

Acceptance uses private runtime/config/rules and copies of all configured Bayes
stores. Test native spamc/spamd classification of GTUBE and a normal message,
then a distinct learning fixture and old-binary access to its new learned state.
Local classification does not certify Internet reputation checks. Preserve all
production policy files and learned data; use native PING/parser checks after
installation so synthetic scoring messages do not train the live classifier.

Sources: [publisher download/signature/checksums](https://spamassassin.apache.org/downloads.cgi),
[release notes](https://spamassassin.apache.org/news.html),
[rule update tool](https://spamassassin.apache.org/full/4.0.x/doc/sa-update.html).
