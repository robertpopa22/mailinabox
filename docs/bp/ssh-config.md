# SSH configuration status

### BP-MIAB-026 — Read effective SSH configuration without requiring daemon runtime state

- Context: A status check needs the effective SSH port while the daemon's runtime-only startup directory may not exist.
- Mistake: Querying only with `sshd -T` can report an unreadable configuration even when the configuration parses and the daemon is otherwise healthy.
- Cause: The test-mode invocation can depend on runtime state that is unnecessary for reading the effective configuration.
- Correct: Prefer `sshd -G` and capture stderr so diagnostics cannot be mistaken for configuration rows. Fall back to `sshd -T` only when the binary explicitly reports that `-G` is an unknown option. Invalid configuration, malformed output, or a missing binary stays unknown; do not turn those failures into a misleading fallback result.
- Proof: `tests/test_ssh_config_value.py` covers effective nondefault ports, invalid configuration without fallback, a missing binary, malformed output, old-binary fallback success and failure, and migration of the existing status overlay hook. `tests/test_ssh_status_unknown.py` preserves warning and firewall behavior when the port remains unknown.
- Directive: MIAB-04, MIAB-06, MIAB-09, MIAB-12.
