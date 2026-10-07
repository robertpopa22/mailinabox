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
