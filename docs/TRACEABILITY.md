# Traceability — best practices to evidence

> Every `BP-MIAB-NNN` in [`../BEST_PRACTICES.md`](../BEST_PRACTICES.md) needs one row here.
> State: **T** = concrete test exists (name it), **P** = enforced by a code pattern or documented procedure,
> **G** = gap (backlog, visible, not coverage). Guard: `python scripts/check_bp_coverage.py`.

| BP | State | Evidence (test path / pattern / procedure) |
|----|-------|---------------------------------------------|
| BP-MIAB-001 | P | Verify target versions and archive checksums; rehearse app database migrations on isolated copies before applying `setup/webmail.sh` and `setup/nextcloud.sh`. |
| BP-MIAB-005 | T/P | `tests/test_php_runtime.py`; validate Roundcube 1.7 `public_html` web root, PHP 8.5 authenticated clone endpoints, nginx syntax and configured FPM stop/start in backup. |
| BP-MIAB-006 | P | `setup/geseidl_edition/nextcloud_compat.py` checks reviewed source hashes, builds a separately named app and preserves the guarded schema migration; NC 34→35 clone login, wrong-password rejection, DAV CRUD and original-data fingerprint comparison. |
| BP-MIAB-007 | P | `setup/geseidl_edition/roundcube_secret.py` captures the existing validated key before code replacement; compare key fingerprints and authenticate webmail after installation. |
| BP-MIAB-008 | T/P | `tests/test_nextcloud_sqlite.py`; additive transaction in `setup/geseidl_edition/nextcloud_sqlite.py`, native expected table DDL, fingerprint/integrity and clone replay. |
| BP-MIAB-009 | T/P | Upstream-based branch `codex/upstream-status-apt`, stdlib `tests/test_apt_updates.py`, zero edition imports; ledger records exact base/commit and prepared vs submitted status. |
| BP-MIAB-010 | P | Builder refuses a compiled CONFIGFILE other than the native default; require isolated native-command/service-hardening proof before deployment, and reset only the target start-limit state during package rollback. |
| BP-MIAB-011 | P | Optional NSD recipe enables RRL defaults; compare native and publisher control/security settings with their parsers and live control status, and carry existing explicit deployment policy forward. |
| BP-MIAB-012 | T/P | `tests/test_bind_defaults.py` simulates ISC removal of Ubuntu default-zone conffiles and verifies conflict refusal; optional `bind_defaults.py` preserves standard zone content under edition-owned paths before installation. Compare pre/post package configuration, not just pre-install candidate binaries. |
| BP-MIAB-013 | T/P | `tests/test_dovecot24.py` covers legacy auth-variable conversion and policy preservation; require a functioning auth-policy HTTP shape and no policy-expansion/fallback errors, plus wrong-password/network/SQL-injection negative canaries. Setup replays only a root-owned private profile checked by the installed parser. |
| BP-MIAB-014 | T/P | `tests/test_postfix_package.py` prevents native absolute symlinks from overwriting host files; retain distribution stato­verride/maintainer scripts and test postqueue as an ordinary user. Build core and SQLite/PCRE modules together, update manuals and verify native path layout. |
| BP-MIAB-015 | T/P | `tests/test_maildb_journal.py` verifies metadata-only migration, idempotence and refusal with an active writer. SQLite maps use non-chroot proxymap. Cold-start old-package recovery must deliver a message created by the new package, preserving its content hash and all database records. |
| BP-MIAB-002 | P | A rehearsal config sets a unique `instanceid` and private `tempdirectory`; copied data/config paths alone do not isolate Nextcloud `FileSequence` locks. |
| BP-MIAB-003 | P | `setup/webmail.sh` explicitly sets main/password config to root:www-data, 0640; verify reads and authenticated webmail access as the service user. |
| BP-MIAB-004 | T | `tests/test_geseidl_reporting.py`: captured SMTP diagnostics and preserved failures; noncontiguous changes; new APT dependencies; held/unknown/reboot states; idempotent hook persistence. |
