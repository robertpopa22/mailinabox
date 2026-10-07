# Optional publisher release channels

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
