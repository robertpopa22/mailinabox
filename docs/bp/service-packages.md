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
