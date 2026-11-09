"""Daily GitHub Models call ledger for ``cassettes-models.yml`` (D900).

The workflow runs in GitHub Actions with ``models: read``; the free tier allows a few hundred
requests per day and 15 per minute. This helper keeps the arithmetic out of YAML:

    python scripts/models/gh_models_budget.py remaining --ledger L --daily-cap 120 --requested 100 \
        [--start-used N] [--day YYYY-MM-DD]
    python scripts/models/gh_models_budget.py add --ledger L --calls 37
    python scripts/models/gh_models_budget.py used --ledger L
    python scripts/models/gh_models_budget.py count --dir D
    python scripts/models/gh_models_budget.py summary --target indomain_dev --calls 37 --hits 80 \
        --used 37 --cap 120

The ledger is one small JSON file (``{"date": "YYYY-MM-DD", "calls": N}``) that the workflow keeps
in ``actions/cache`` under a per-day key, so a new UTC day starts at zero. It is a SOFT counter
(a lost cache entry resets it); a ledger that exists but is corrupt fails closed
(``remaining`` prints 0). It holds no secret.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path


class LedgerError(RuntimeError):
    """The ledger file exists but cannot be read: the day's budget is unknown (fail closed)."""


def today() -> str:
    """The current UTC date as ``YYYY-MM-DD`` (the quota day of the ledger)."""
    return datetime.now(UTC).date().isoformat()


def used_today(ledger: Path, day: str) -> int:
    """Calls already recorded for ``day``.

    Args:
        ledger: Path of the JSON ledger file.
        day: ``YYYY-MM-DD``.

    Returns:
        The number of calls made on ``day``; 0 for a missing ledger or one of another day.

    Raises:
        LedgerError: The file exists but is not a valid ledger (the budget is then unknown).
    """
    if not ledger.exists():
        return 0
    try:
        doc = json.loads(ledger.read_text(encoding="utf-8"))
        return int(doc["calls"]) if doc["date"] == day else 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        msg = f"ledger {ledger} is unreadable"
        raise LedgerError(msg) from exc


def remaining(used: int, daily_cap: int, requested: int, start_used: int | None = None) -> int:
    """Calls this step may make, never negative.

    ``requested`` is the budget of the whole run; ``start_used`` is the day's total when the run
    started, so calls made by earlier stages of the same run are deducted (``None``: the run is
    taken to have made none yet).

    Examples:
        >>> remaining(used=30, daily_cap=120, requested=100)
        90
        >>> remaining(used=30, daily_cap=120, requested=50)
        50
        >>> remaining(used=130, daily_cap=120, requested=50)
        0
        >>> remaining(used=70, daily_cap=120, requested=50, start_used=30)
        10
    """
    done = 0 if start_used is None else max(0, used - start_used)
    run_left = requested - done
    return max(0, min(run_left, daily_cap - used))


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


def _ledger_command(args: argparse.Namespace, day: str) -> str:
    """Run one of the ledger sub-commands (``remaining``, ``add``, ``used``) for ``day``."""
    if args.cmd == "remaining":
        used = used_today(args.ledger, day)
        return str(remaining(used, args.daily_cap, args.requested, args.start_used))
    if args.cmd == "add":
        return str(add_calls(args.ledger, day, args.calls))
    return str(used_today(args.ledger, day))


def main(argv: Sequence[str]) -> int:
    """Entry point; prints the result of the sub-command to stdout and returns the exit code."""
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    rem = sub.add_parser("remaining")
    rem.add_argument("--ledger", type=Path, required=True)
    rem.add_argument("--daily-cap", type=int, required=True)
    rem.add_argument("--requested", type=int, required=True)
    rem.add_argument("--start-used", type=int, default=None)
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
    for p in (rem, add, usd):
        p.add_argument("--day", default=None, help="quota day (the start date of the run)")
    args = ap.parse_args(list(argv))
    if args.cmd == "count":
        out = str(count_files(args.dir))
    elif args.cmd == "summary":
        out = summary_line(args.target, args.calls, args.hits, args.used, args.cap)
    else:
        try:
            out = _ledger_command(args, args.day or today())
        except LedgerError as exc:
            sys.stderr.write(f"::error::{exc}; failing closed\n")
            if args.cmd != "remaining":
                return 1
            out = "0"
    sys.stdout.write(out + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
