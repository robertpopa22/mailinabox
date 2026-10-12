# BP-MIAB-023 — Report current state with a verifiable source

Comparing a fork-only SHA through the upstream repository API can return HTTP404
even when the local fork and upstream are valid. Resolve the exact validated
GitHub origin and compare that SHA in the fork namespace against upstream main.
An unavailable comparison stays warning; do not hide genuine security changes.

Keep AI timeout totals over24h as history and assess current errors separately
over one hour. Recovery needs a real model result later than the last failure;
uncertainty and a skipped classification do not prove recovery. Conventional
filters and their independent health remain in force.

Evidence: `tests/test_alert_reporting.py`, `tests/test_geseidl_status.py`.
Production activation is recorded in the private deployment repository.
