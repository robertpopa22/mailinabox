# Scheduled verification repair — 2026-09-29

`management/status_checks.py` must have an LF shebang. `.gitattributes` enforces it after a Windows checkout; CRLF prevented direct execution despite an existing interpreter.

`setup/dns.sh` installs a cron entry calling `dnssec_checked.py`. Successful stdout goes to syslog (`geseidl-dnssec`); stderr, failed exit status and timeout remain visible to cron. The child deadline is 600 seconds. Regression: `tests/test_dnssec_checked.py`.
