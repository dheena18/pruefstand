"""Daily GitHub Models call ledger for ``cassettes-models.yml`` (D900).

The workflow runs in GitHub Actions with ``models: read``; the free tier allows a few hundred
requests per day and 15 per minute. This helper keeps the arithmetic out of YAML:

    python scripts/models/gh_models_budget.py remaining --ledger L --daily-cap 120 --requested 100
    python scripts/models/gh_models_budget.py add --ledger L --calls 37
    python scripts/models/gh_models_budget.py used --ledger L
    python scripts/models/gh_models_budget.py count --dir D
    python scripts/models/gh_models_budget.py summary --target indomain_dev --calls 37 --hits 80 \
        --used 37 --cap 120

The ledger is one small JSON file (``{"date": "YYYY-MM-DD", "calls": N}``) that the workflow keeps
in ``actions/cache`` under a per-day key, so a new UTC day starts at zero. It holds no secret.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path


def today() -> str:
    """The current UTC date as ``YYYY-MM-DD`` (the quota day of the ledger)."""
    return datetime.now(UTC).date().isoformat()


def used_today(ledger: Path, day: str) -> int:
    """Calls already recorded for ``day``; 0 for a missing, unreadable or older ledger.

    Args:
        ledger: Path of the JSON ledger file.
        day: ``YYYY-MM-DD``.

    Returns:
        The number of calls made on ``day``.
    """
    try:
        doc = json.loads(ledger.read_text(encoding="utf-8"))
        return int(doc["calls"]) if doc.get("date") == day else 0
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return 0


def remaining(used: int, daily_cap: int, requested: int) -> int:
    """Calls this step may make: ``min(requested, daily_cap - used)``, never negative.

    Examples:
        >>> remaining(used=30, daily_cap=120, requested=100)
        90
        >>> remaining(used=30, daily_cap=120, requested=50)
        50
        >>> remaining(used=130, daily_cap=120, requested=50)
        0
    """
    return max(0, min(requested, daily_cap - used))


def add_calls(ledger: Path, day: str, calls: int) -> int:
    """Add ``calls`` to the ledger of ``day`` and return the new total.

    Args:
        ledger: Path of the JSON ledger file (parent directory is created).
        day: ``YYYY-MM-DD``.
        calls: Calls made since the last update (negative values count as 0).

    Returns:
        Total calls recorded for ``day``.
    """
    total = used_today(ledger, day) + max(0, calls)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(json.dumps({"date": day, "calls": total}) + "\n", encoding="utf-8")
    return total


def count_files(directory: Path, pattern: str = "*.json") -> int:
    """Number of files below ``directory`` matching ``pattern`` (0 if it does not exist)."""
    return sum(1 for p in directory.rglob(pattern) if p.is_file()) if directory.is_dir() else 0


def hit_ratio(hits: int, calls: int) -> float:
    """Share of answers served from the cache: ``hits / (hits + calls)``; 0.0 when both are 0.

    Examples:
        >>> hit_ratio(hits=80, calls=20)
        0.8
        >>> hit_ratio(hits=0, calls=0)
        0.0
    """
    total = hits + calls
    return hits / total if total else 0.0


def summary_line(target: str, calls: int, hits: int, used: int, cap: int) -> str:
    """One Markdown table row for the job summary (no secrets, only counts)."""
    ratio = f"{hit_ratio(hits, calls):.0%}"
    return f"| {target} | {calls} | {hits} | {ratio} | {used} / {cap} |"


def main(argv: Sequence[str]) -> int:
    """Entry point; prints the result of the sub-command to stdout and returns the exit code."""
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    rem = sub.add_parser("remaining")
    rem.add_argument("--ledger", type=Path, required=True)
    rem.add_argument("--daily-cap", type=int, required=True)
    rem.add_argument("--requested", type=int, required=True)
    add = sub.add_parser("add")
    add.add_argument("--ledger", type=Path, required=True)
    add.add_argument("--calls", type=int, required=True)
    usd = sub.add_parser("used")
    usd.add_argument("--ledger", type=Path, required=True)
    cnt = sub.add_parser("count")
    cnt.add_argument("--dir", type=Path, required=True)
    summ = sub.add_parser("summary")
    for name in ("calls", "hits", "used", "cap"):
        summ.add_argument(f"--{name}", type=int, required=True)
    summ.add_argument("--target", required=True)
    args = ap.parse_args(list(argv))
    out: str
    if args.cmd == "remaining":
        out = str(remaining(used_today(args.ledger, today()), args.daily_cap, args.requested))
    elif args.cmd == "add":
        out = str(add_calls(args.ledger, today(), args.calls))
    elif args.cmd == "used":
        out = str(used_today(args.ledger, today()))
    elif args.cmd == "count":
        out = str(count_files(args.dir))
    else:
        out = summary_line(args.target, args.calls, args.hits, args.used, args.cap)
    sys.stdout.write(out + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
