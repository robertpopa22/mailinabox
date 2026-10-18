# Status reporting

### BP-MIAB-004 — Report structured checks and complete grouped changes
- Context: the daily report included a successful `nc` diagnostic and several repeated Added headings in one category.
- Mistake: inheriting the diagnostic subprocess's stderr and emitting one heading per sequence-diff opcode. APT diagnostic text could also be counted as a package, while newly installed dependencies lacked a parsed current version.
- Cause: mixing process output with the buffered status report, fragmented presentation and an overly narrow installation-record parser.
- Correct: capture probe diagnostics and preserve its exit code; consolidate every changed item into at most one Previous and one Current block per category. Count only valid APT Inst records, include new dependencies without allowing removals, and display held candidates separately. An unknown hold state stays a warning, and reboot and pending-package states can both remain visible.
- Proof: `tests/test_geseidl_reporting.py` exercises real fragmentation, success/failure capture, APT package records, policy holds, unknown state, reboot and reapplying/removing the hooks against the actual source.
- Directive: MIAB-01, MIAB-03, MIAB-06, MIAB-09.


### BP-MIAB-021 — Retired classifier health

Effective `enabled=false` means an optional classifier was disabled explicitly.
Historical model timeouts remain informational; they cannot demand a later model
success after retirement. Unknown configuration remains actionable, and failures
of active mail filters retain their original severity. The regression test covers
disabled, unknown and already-critical states; a cloned reporter with read-only
live collectors and intercepted send/save validates the deployment separately.

### BP-MIAB-024 — DMARC digests and uncertain dispatch

An unfamiliar source address is not itself proof of a DMARC authentication
failure. Only reports whose sole code is `unexpected_source_ip`, with full
reject policy and at least one aligned passing mechanism on every record,
may enter the daily digest. Failed alignment, adverse disposition, partial or
different policy, and report errors retain immediate notification.

The SQLite queue stores report metadata before archiving the untouched original.
The digest hour and IANA timezone are configurable through
`DMARC_ALERTS_DIGEST_HOUR` (default8) and `DMARC_ALERTS_DIGEST_TZ` (defaultUTC).
Reports arriving after the daily cutoff wait for the next day; a missed digest
is picked up later, with at most one batch per local day.

Reserve each report in an outbox before dispatch. A timeout or crash after
reservation remains `uncertain`; do not automatically resend it. The monitor
returns a failing status until an operator reconciles those rows with the mail
queue/logs. A confirmed local sendmail submission proves queue acceptance, not
recipient delivery. The original source-IP allowlist is unchanged.

Migration is additive. Retain the SQLite state and archive when restoring the
previous code; any queued digest or uncertain outbox requires explicit review
and must not be discarded or silently replayed. Tests use documentation addresses
and intercepted submission/move operations, including crash and restart cases.
