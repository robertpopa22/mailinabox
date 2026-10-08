# Native service integration

## BP-MIAB-010 — Test implicit daemon defaults and hardened startup

A daemon answering an isolated fixture with `-c` does not prove its native service
can start without that option. NSD appends `/nsd` to `sysconfdir`; configuring
`/etc/nsd` compiled an incorrect `/etc/nsd/nsd/nsd.conf` default. Explicit config
tests hid this error. The builder now uses `/etc`, validates the generated
CONFIGFILE constant and requires a separate native-command/hardening test using
private network and filesystem mounts before production.

Rapid failed automatic restarts can trigger systemd's start limit. A package
rollback must record its progress before recovery, reset only the target service's
failed/start-limit state, then verify the restored daemon. Keep attempt-specific
backup paths and never overwrite DNS zones or new mail merely to restore a binary.
Directive: MIAB-03, MIAB-07, MIAB-09, MIAB-12.

## BP-MIAB-011 — Preserve effective policy across package origins

Unchanged config and native unit bytes do not guarantee unchanged policy. Ubuntu
enabled NSD control and response-rate limiting implicitly, while the publisher
source disabled both by default. Compare effective settings using both versions'
parsers, then validate the running daemon. General management control belongs in
upstream configuration; the optional edition package preserves native RRL
defaults, and deployment-specific values stay explicit outside the public source.
Directive: MIAB-03, MIAB-05, MIAB-07, MIAB-12.
## BP-MIAB-012 — Test native conffile removal during origin changes

- Context: switching BIND from Ubuntu 9.18 packages to ISC stable 9.20 packages.
- Mistake: testing candidate binaries with the old configuration passed, but the
  package installation removed obsolete default-zone files and replaced an
  unmodified main configuration.
- Cause: a runtime-only clone omitted native package conffile lifecycle changes.
- Correct: inspect maintainer scripts and conffile lists; preserve existing
  standard zone content in edition-owned files before changing package origin.
  Use `--force-confold`, verify the effective configuration after installation,
  and retain authenticated old packages for bounded recovery.
- Proof: `tests/test_bind_defaults.py` simulates obsolete-file removal and
  refuses conflicting edition files before changing the main configuration;
  isolated native startup/DNSSEC and old-package recovery remain required.
- Directive: MIAB-11, MIAB-12.

## BP-MIAB-013 — Verify authentication policy beyond login success

A Dovecot login can succeed after auth-policy evaluation fails and falls back.
Legacy long variables such as `%{rip}` are removed in 2.4, even when the typed
configuration parser accepts their strings. Convert long and short variables;
validate the actual HTTP request schema and inspect policy errors. Combine this
with wrong-password, source-network and SQL-injection negative controls.

Runtime paths include the instance registry, spool, logs and Unix sockets. Do not
copy ephemeral sockets as persisted state. Native service properties unavailable
through transient D-Bus units need an actual native-unit fixture. Test the final
storage format, then recover old authenticated packages with new mail retained.
Keep UIDVALIDITY/UIDs and verify Sieve/auth/quotas after recovery. A Sieve editor
accepting a literal redirect does not imply execution is allowed; test runtime
prohibition, local keep and an empty isolated outbound queue.
Directive: MIAB-03, MIAB-05, MIAB-07, MIAB-11, MIAB-12.

## BP-MIAB-014 — Preserve package boundaries and symlink safety

Native packages can contain absolute symlinks. A build that copies through one
can overwrite the host rather than its staging tree. Refuse symlinked parents
and replace destination links safely. Build all executable/shared-library/plugin
ABI from one publisher source and preserve native service/maintainer integration.
Native Debian Postfix stato­verride initializes postdrop/postqueue permissions;
an extracted binary is not an installed package. Test an ordinary service user,
not just root. Inspect actual publisher script paths and ship matching manuals.
Directive: MIAB-03, MIAB-07, MIAB-11.

## BP-MIAB-015 — Test read-only SQLite consumers after a cold restart

SQLite WAL readers need existing readable side files, or permission to create
them. Successful lookups while a privileged writer is connected do not prove a
cold start. Chroot adds another boundary: use non-chroot proxymap for the four
read-only address/domain lookup maps, without weakening daemon isolation.

For a small user database with read-only mail consumers, an explicit operator
migration to rollback journaling can remove that dependency. Stop consumers,
take a coherent backup, compare every table's records and integrity before/after,
and refuse active transactions. Do not grant mail daemons write access to user
credentials or restore an old database. This is separate from webmail/Nextcloud
databases and is never an automatic package postinst or routine setup action.
Prove new-version cold startup, old-version delivery of newly queued mail and
content preservation. Keep any unresolved mode or recovery limitation visible.
Directive: MIAB-03, MIAB-07, MIAB-11, MIAB-12.

## BP-MIAB-017 — Isolate native service directory lifecycle

Network and mount namespaces do not isolate systemd's host-side handling of
RuntimeDirectory and StateDirectory. A copied unit retaining the production
directory name can remove the production control socket when its fixture stops.
Override these names with unique fixture directories, bind only the private
runtime/state and verify the original live socket inode and a functioning control
request after cleanup. Preserve native hardening independently of this override.

Ban commands and jail startup do not prove completed kernel enforcement. Test
an allowed source and a banned source with actual connections in the private
network; inspect the effective backend, which may change between vendor releases.
Wait for asynchronous restoration before comparing persisted bans. Socket
activation needs stop/restart proof as well as initial startup: shutdown of an
inherited FD can invalidate the original systemd listener.
Directive: MIAB-03, MIAB-07, MIAB-11.

## BP-MIAB-018 — Prove cross-version persistence and numeric semantics

A newer binary can write an RDB format the recovery binary cannot read. Prepare
plain-command AOF on the running old Redis, wait for successful rewrite and
verify the base file before persisting configuration or replacing packages.
Setting appendonly in an offline config alone does not create a complete journal.
Keep current AOF/new writes during recovery; never restore an old snapshot over
new activity. The tested workload uses existing core data types, without newly
introduced commands/types that the recovery binary cannot interpret.

Compare each type's logical values and absolute expiration times. Floating-point
score text can change between versions while the IEEE754 value remains exactly
the same; normalize to exact hexadecimal representation, with no rounding or
tolerance. Keep all other byte comparisons strict. Report short-lived keys
excluded by an explicit fixed deadline separately. A built-in vectorset entry
in MODULE LIST is distinct from loading external optional module libraries.
Directive: MIAB-03, MIAB-07, MIAB-11, MIAB-12.

## BP-MIAB-019 — Validate complete helper cohorts and controlled learning fixtures

Updating a main package without an exact-version helper can cause APT to remove
that helper. Inspect the complete dependency cohort and reject removals. Preserve
native file ownership boundaries; adding a helper to two packages creates an
unpack conflict. New staging directories inherit the builder umask, so explicitly
set package directory permissions and test an ordinary service account.

An updater started with a candidate library may execute its lint subprocess
against the installed old library. Isolate the full executable/library cohort,
not just the top-level command. Keep source-signing and rule-update keys distinct,
verify both and stage rules in their version-specific directory before startup.

Do not copy transient GPG Unix sockets as persisted state. Classifier training
changes the model: a learning fixture sharing vocabulary with a healthy fixture
can invalidate that fixture's label. Use separate data, disable uncontrolled
learning in the rehearsal and verify the actual documented counter columns.
Test new training retained by the recovery binary; production tests use PING and
parser checks rather than polluting the live model with synthetic messages.
Directive: MIAB-03, MIAB-07, MIAB-11, MIAB-12.

## BP-MIAB-016 — Preserve listener scope and verify actual protocol methods

nginx 1.25.1 introduced the server-level HTTP/2 directive. Converting a legacy
socket flag blindly can widen protocol scope when a server has mixed listeners.
Preserve the older path, parse block/quoted/comment boundaries, reject ambiguous
scope or conflicting policy and verify replay before using the current syntax.
Keep native TLS/server configuration and package conffile lifecycle evidence.

A client using a data option sends POST even with an empty body. A test labelled
GET/POST must verify the observed request method, not infer it from body length.
Use a private FPM socket/session/cache and read-only application data; network
namespaces alone do not isolate host Unix sockets. Test actual TLS name/chain,
ALPN, FastCGI and body buffering, then repeat with the recovery binary/config.
Directive: MIAB-03, MIAB-07, MIAB-11, MIAB-12.
