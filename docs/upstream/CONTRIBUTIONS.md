# Upstream relationship and contribution ledger

Decision: MIAB-12. Upstream remains `mail-in-a-box/mailinabox`; the edition does
not replace its product goals or supported installation defaults.

## Working structure

1. **General fixes:** small commits based on a recorded upstream object ID, CC0
   where required by upstream CONTRIBUTING.md, with tests that work without this
   edition. A prepared branch or patch is not a submitted pull request.
2. **Version compatibility:** select configuration by detected component version,
   preserve the upstream-supported path, and demonstrate migration/recovery.
   Optional publisher package channels do not become upstream defaults.
3. **Geseidl package:** `management/geseidl_edition` and
   `setup/geseidl_edition` hold local policies, provisioning and runtime adapters.
   Packaging these directories must not silently run production migrations on
   package installation. A future binary package remains a separate deliverable.

## Ledger

| Candidate | Upstream base | State | Evidence / next action |
|---|---|---|---|
| Parse only APT installation records, including newly introduced dependencies | df7f245e0e54e7b5292837504422a97999ee33f3 | prepared | Branch `codex/upstream-status-apt`, commit3124f87d64e0c5bc395c360e022e3425aff6323b; four stdlib regression tests pass without any edition module. Patch under `docs/upstream/patches`. No PR submitted. |
| Explicitly enable local NSD management control instead of relying on distribution defaults | df7f245e0e54e7b5292837504422a97999ee33f3 | prepared | Branch `codex/upstream-nsd-control`, commitsc9e3e9c/2559a95; actual NSD4.15 parser test and Linux shell syntax pass without the edition. Cherry-picked locally asb0ab0bb. No PR submitted. |
| Proxy read-only SQLite address/domain lookups across the chroot boundary | df7f245e0e54e7b5292837504422a97999ee33f3 | prepared | Branch `codex/upstream-sqlite-proxy`, commit716aa7bad073ca03c1a5ed452c17207a79668a77; two stdlib SQLite/chroot boundary tests pass on Linux root without edition modules or marker. These do not start Postfix; native Postfix3.8.6/3.11.7 map/SMTP/cold-start/queue-recovery probes are separate deployment acceptance. Four general setup changes already applied locally; package channels/journal policy stay optional. No PR submitted. |
| Latest mail/DNS components with version-aware configuration | df7f245 | in progress | NSD4.15.2, BIND9.20.29, Dovecot2.4.5 and Postfix3.11.7 native integration/recovery tested; control/RRL, authentication, data and queue preserved. nginx/Redis/Fail2ban support migrations remain open. |

For each eventual contribution record the full base SHA, branch, tests, PR URL if
submitted, upstream outcome and the local duplicate retired after acceptance.
Release versions are reverified from publisher sources at execution time.
