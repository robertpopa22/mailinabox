# Best practices — index

> Charter: [`CHARTER.md`](CHARTER.md) (directive MIAB-09). This file is an **index**: one row per lesson.
> Details live in `docs/bp/<category>.md` (split a category file when it passes ~300 lines).
> Coverage of each lesson (test / pattern / gap) is tracked in [`docs/TRACEABILITY.md`](docs/TRACEABILITY.md);
> `python scripts/check_bp_coverage.py` fails when an ID below has no row there.

## Format of a lesson (in `docs/bp/<category>.md`)

```
### BP-MIAB-NNN — <title>
- Context: where it happened
- Mistake: what went wrong
- Cause: why
- Correct: what to do instead
- Proof: the test or control that prevents a repeat
- Directive: MIAB-NN (if a rule came out of it)
```

## Index

| ID | Title | Category | Link |
|----|-------|----------|------|
| BP-MIAB-001 | Review release pins as well as the fork Git head | Updates | [Details](docs/bp/updates.md) |
| BP-MIAB-005 | Validate major-version web roots and runtime backup coherence | Updates | [Details](docs/bp/latest-stable.md) |
| BP-MIAB-006 | Maintain compatible authentication without changing user identities | Updates | [Details](docs/bp/latest-stable.md) |
| BP-MIAB-007 | Preserve the webmail cipher key across software updates | Updates | [Details](docs/bp/latest-stable.md) |
| BP-MIAB-008 | Validate additive SQLite schema guarantees | Updates | [Details](docs/bp/latest-stable.md) |
| BP-MIAB-009 | Prove upstream portability without the edition | Contributions | [Details](docs/bp/upstream.md) |
| BP-MIAB-010 | Test implicit daemon defaults and hardened startup | Packaging | [Details](docs/bp/service-packages.md) |
| BP-MIAB-011 | Preserve effective policy across package origins | Packaging | [Details](docs/bp/service-packages.md) |
| BP-MIAB-012 | Test native conffile removal during origin changes | Packaging | [Details](docs/bp/service-packages.md) |
| BP-MIAB-013 | Verify authentication policy beyond login success | Packaging | [Details](docs/bp/service-packages.md) |
| BP-MIAB-014 | Preserve package boundaries and symlink safety | Packaging | [Details](docs/bp/service-packages.md) |
| BP-MIAB-015 | Test read-only SQLite consumers after a cold restart | Packaging | [Details](docs/bp/service-packages.md) |
| BP-MIAB-016 | Preserve listener scope and verify actual protocol methods | Packaging | [Details](docs/bp/service-packages.md) |
| BP-MIAB-017 | Isolate native service directory lifecycle | Packaging | [Details](docs/bp/service-packages.md) |
| BP-MIAB-018 | Prove cross-version persistence and numeric semantics | Packaging | [Details](docs/bp/service-packages.md) |
| BP-MIAB-019 | Validate complete helper cohorts and controlled learning fixtures | Packaging | [Details](docs/bp/service-packages.md) |
| BP-MIAB-002 | Isolate clone instance IDs and temporary state | Updates | [Details](docs/bp/updates.md#bp-miab-002--isolate-clone-instance-ids-and-temporary-state) |
| BP-MIAB-003 | Set generated webmail config readability explicitly | Updates | [Details](docs/bp/updates.md#bp-miab-003--set-generated-webmail-config-readability-explicitly) |
| BP-MIAB-004 | Report structured checks and complete grouped changes | Reporting | [Details](docs/bp/reporting.md) |
