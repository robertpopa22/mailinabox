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
