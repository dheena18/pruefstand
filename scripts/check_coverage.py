"""Enforce the coverage gate defined in CLAUDE.md §6 on ``coverage.json`` (T0.1 S10).

The thresholds below are CLAUDE.md §6 (D130, the single definition). If this file and CLAUDE.md
ever differ, CLAUDE.md wins and this file is fixed.
"""

import argparse
import json
import re
from collections.abc import Sequence
from pathlib import Path

# --- CLAUDE.md §6: >= 90 % for each of pruefstand/{core,gate,metrics,perturb}; >= 80 % overall,
# --- computed separately for `pruefstand` and for `rag_demo`; src only.
FLOORS = {"core": 90.0, "gate": 90.0, "metrics": 90.0, "perturb": 90.0}
OVERALL_FLOOR = 80.0
OVERALL_PACKAGES = ("pruefstand", "rag_demo")

Counts = tuple[int, int]  # (covered, total) incl. branches, as coverage.py defines percent_covered


def _counts(summary: dict[str, int]) -> Counts:
    covered = summary["covered_lines"] + summary.get("covered_branches", 0)
    total = summary["num_statements"] + summary.get("num_branches", 0)
    return covered, total


def aggregate(files: dict[str, dict[str, dict[str, int]]]) -> dict[str, Counts]:
    """Sum covered/total per gate key (``pruefstand/core``, ``pruefstand``, ``rag_demo``, ...)."""
    sums: dict[str, Counts] = {}
    for name, data in files.items():
        match = re.search(r"(?:^|/)src/(pruefstand|rag_demo)/(?:(\w+)/)?", name)
        if not match:
            continue
        package, sub = match.group(1), match.group(2)
        keys = [package]
        if package == "pruefstand" and sub in FLOORS:
            keys.append(f"pruefstand/{sub}")
        covered, total = _counts(data["summary"])
        for key in keys:
            c0, t0 = sums.get(key, (0, 0))
            sums[key] = (c0 + covered, t0 + total)
    return sums


def evaluate(sums: dict[str, Counts]) -> tuple[list[str], list[str]]:
    """Return (table rows, violations); a key with zero statements is skipped."""
    limits = {f"pruefstand/{k}": v for k, v in FLOORS.items()}
    limits |= dict.fromkeys(OVERALL_PACKAGES, OVERALL_FLOOR)
    rows, violations = [], []
    for key, floor in limits.items():
        covered, total = sums.get(key, (0, 0))
        if total == 0:
            rows.append(f"{key:<22} skipped (0 statements)")
            continue
        pct = round(covered / total * 100, 1)
        rows.append(f"{key:<22} {pct:5.1f}%  (floor {floor:g}%)")
        if pct < floor:
            violations.append(f"{key} {pct}% < {floor:g}%")
    return rows, violations


def main(argv: Sequence[str] | None = None) -> int:
    """Read ``coverage.json``, print the table, return 1 on any violation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, default=Path("coverage.json"))
    args = parser.parse_args(argv)
    report = json.loads(args.file.read_text(encoding="utf-8"))
    rows, violations = evaluate(aggregate(report["files"]))
    print("\n".join(rows))
    for violation in violations:
        print(f"FAIL {violation}")
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
