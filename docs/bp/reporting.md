# Status reporting

### BP-MIAB-004 — Report structured checks and complete grouped changes
- Context: the daily report included a successful `nc` diagnostic and several repeated Added headings in one category.
- Mistake: inheriting the diagnostic subprocess's stderr and emitting one heading per sequence-diff opcode. APT diagnostic text could also be counted as a package, while newly installed dependencies lacked a parsed current version.
- Cause: mixing process output with the buffered status report, fragmented presentation and an overly narrow installation-record parser.
- Correct: capture probe diagnostics and preserve its exit code; consolidate every changed item into at most one Previous and one Current block per category. Count only valid APT Inst records, include new dependencies without allowing removals, and display held candidates separately. An unknown hold state stays a warning, and reboot and pending-package states can both remain visible.
- Proof: `tests/test_geseidl_reporting.py` exercises real fragmentation, success/failure capture, APT package records, policy holds, unknown state, reboot and reapplying/removing the hooks against the actual source.
- Directive: MIAB-01, MIAB-03, MIAB-06, MIAB-09.
