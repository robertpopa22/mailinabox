# Traceability — best practices to evidence

> Every `BP-MIAB-NNN` in [`../BEST_PRACTICES.md`](../BEST_PRACTICES.md) needs one row here.
> State: **T** = concrete test exists (name it), **P** = enforced by a code pattern or documented procedure,
> **G** = gap (backlog, visible, not coverage). Guard: `python scripts/check_bp_coverage.py`.

| BP | State | Evidence (test path / pattern / procedure) |
|----|-------|---------------------------------------------|
| BP-MIAB-001 | P | Verify target versions and archive checksums; rehearse app database migrations on isolated copies before applying `setup/webmail.sh` and `setup/nextcloud.sh`. |
| BP-MIAB-002 | P | A rehearsal config sets a unique `instanceid` and private `tempdirectory`; copied data/config paths alone do not isolate Nextcloud `FileSequence` locks. |
| BP-MIAB-003 | P | `setup/webmail.sh` explicitly sets main/password config to root:www-data, 0640; verify reads and authenticated webmail access as the service user. |
| BP-MIAB-004 | T | `tests/test_geseidl_reporting.py`: captured SMTP diagnostics and preserved failures; noncontiguous changes; new APT dependencies; held/unknown/reboot states; idempotent hook persistence. |
