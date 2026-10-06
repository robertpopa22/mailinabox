#!/usr/bin/env python3
"""Fail when a BP-MIAB-NNN listed in BEST_PRACTICES.md has no row in docs/TRACEABILITY.md.

A BP counts as listed when its ID appears in a table row (a line starting with '|')
of BEST_PRACTICES.md; it counts as covered when its ID appears in a table row of
docs/TRACEABILITY.md. Exit code 0 = all covered, 1 = missing coverage or unreadable input.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

BP_ID = re.compile(r"\bBP-MIAB-\d{3}\b")
ROOT = Path(__file__).resolve().parents[1]


def table_ids(path: Path) -> set[str]:
    ids: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("|"):
            ids.update(BP_ID.findall(line))
    return ids


def main() -> int:
    index = ROOT / "BEST_PRACTICES.md"
    trace = ROOT / "docs" / "TRACEABILITY.md"
    for path in (index, trace):
        if not path.is_file():
            print(f"ERROR: missing {path.relative_to(ROOT)}", file=sys.stderr)
            return 1
    listed = table_ids(index)
    covered = table_ids(trace)
    missing = sorted(listed - covered)
    orphan = sorted(covered - listed)
    for bp in missing:
        print(f"MISSING: {bp} is in BEST_PRACTICES.md but has no row in docs/TRACEABILITY.md")
    for bp in orphan:
        print(f"WARNING: {bp} is in docs/TRACEABILITY.md but not in the BEST_PRACTICES.md index")
    print(f"{len(listed)} BP listed, {len(listed) - len(missing)} covered, {len(missing)} missing")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
