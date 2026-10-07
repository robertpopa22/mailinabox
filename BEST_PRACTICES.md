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
| BP-MIAB-002 | Isolate clone instance IDs and temporary state | Updates | [Details](docs/bp/updates.md#bp-miab-002--isolate-clone-instance-ids-and-temporary-state) |
| BP-MIAB-003 | Set generated webmail config readability explicitly | Updates | [Details](docs/bp/updates.md#bp-miab-003--set-generated-webmail-config-readability-explicitly) |
| BP-MIAB-004 | Report structured checks and complete grouped changes | Reporting | [Details](docs/bp/reporting.md) |
