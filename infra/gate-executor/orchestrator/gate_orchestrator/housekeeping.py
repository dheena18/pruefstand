"""Housekeeping phases at the end of the nightly (T6.2b S4; ci-cd.md section 1.2, D1028).

``runs-prune``: of the run directories in ``$PRUEFSTAND_HOME/runs/``, nightly and release runs
beyond the newest 90 and every other run older than 14 days are removed (a directory without a
readable ``run.json`` is left alone). ``repo-size``: the private executor repo must stay under
1 GB (``GET /repos/<owner>/pruefstand-gate`` ``size`` in KB); above it the phase fails loudly in
the summary. Both are informational for the night's status.
"""

import json
import shutil
from datetime import datetime, timedelta
from pathlib import Path

KEEP_NIGHTLY = 90
KEEP_OTHER = timedelta(days=14)
MAX_REPO_KB = 1024 * 1024


def runs_to_prune(runs: Path, now: datetime) -> list[Path]:
    """The run directories ``runs-prune`` removes (oldest first)."""
    nightly: list[tuple[str, Path]] = []
    old: list[Path] = []
    for run_json in sorted(runs.glob("*/run.json")) if runs.is_dir() else []:
        try:
            data = json.loads(run_json.read_text(encoding="utf-8"))
            created = datetime.fromisoformat(str(data["created_at"]))
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if data.get("workload") == "nightly":
            nightly.append((str(data.get("run_id", run_json.parent.name)), run_json.parent))
        elif created.tzinfo is not None and now - created > KEEP_OTHER:
            old.append(run_json.parent)
    nightly.sort()
    return [p for _, p in nightly[:-KEEP_NIGHTLY]] + old


def prune_runs(runs: Path, now: datetime) -> list[str]:
    """Remove :func:`runs_to_prune`; return the removed directory names."""
    removed = []
    for path in runs_to_prune(runs, now):
        shutil.rmtree(path)
        removed.append(path.name)
    return removed


def repo_size_line(size_kb: int) -> tuple[bool, str]:
    """``(ok, summary line)`` for the private repo's size."""
    ok = size_kb <= MAX_REPO_KB
    head = "repo-size" if ok else "repo-size FAILED"
    return ok, f"{head}: pruefstand-gate is {size_kb / 1024:.0f} MB (limit 1024 MB)"
