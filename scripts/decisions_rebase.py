"""Carry a stale PR's decision rows over to the file layout (D1211).

A PR branched before D1211 appends ``| D<n> | ... |`` rows to the old ``docs/decisions.md``. This
helper does, safely and in one step, what the recipe in ``docs/decisions.md`` describes: take the
PR's own copy of the old page (``HEAD``), move its rows into ``docs/decisions/D<n>.md``
(idempotent),
replace the page by the one of the base ref, and print what else the PR changed on the old page
(pinned versions, prose), which cannot be carried over automatically.
"""

import difflib
import subprocess
import tempfile
from pathlib import Path

from decisions_files import CONFLICT_RE, ConflictMarkerError, DecisionError
from decisions_migrate import find_rows, migrate

PAGE = "docs/decisions.md"


def _git(repo: Path, *args: str) -> str:
    cmd = ["git", "-C", str(repo), *args]
    done = subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603
    if done.returncode:
        msg = f"git {' '.join(args)} failed: {done.stderr.strip()}"
        raise DecisionError(msg)
    return done.stdout


def _non_rows(text: str) -> list[str]:
    drop = {r.line_no for r in find_rows(text)}
    return [ln for i, ln in enumerate(text.split("\n")) if i not in drop]


def rebase_pending(repo: Path, base_ref: str = "origin/main") -> tuple[list[str], str]:
    """Move the PR's rows into files and switch the page to ``base_ref``'s version.

    Args:
        repo: Repository root (the PR branch is checked out; its ``HEAD`` is the PR side).
        base_ref: The ref that holds the new layout (``origin/main``).

    Returns:
        ``(ids of newly written files, unified diff of the PR's non-row edits of the old page)``;
        the diff is empty when the PR changed nothing else there.

    Raises:
        ConflictMarkerError: when the PR's copy holds conflict markers (nothing is changed).
        DecisionError: on an id clash or a duplicate id (nothing is changed), or a git failure.
    """
    mine = _git(repo, "show", f"HEAD:{PAGE}")
    if CONFLICT_RE.search(mine):
        msg = "HEAD:docs/decisions.md contains conflict markers"
        raise ConflictMarkerError(msg)
    base = _git(repo, "merge-base", "HEAD", base_ref).strip()
    old = _git(repo, "show", f"{base}:{PAGE}")
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "decisions.md"
        copy.write_text(mine, encoding="utf-8")
        written = migrate(copy, repo / "docs" / "decisions")
    _git(repo, "checkout", base_ref, "--", PAGE)
    diff = difflib.unified_diff(
        _non_rows(old),
        _non_rows(mine),
        "docs/decisions.md@merge-base",
        "docs/decisions.md@PR",
        lineterm="",
        n=0,
    )
    return written, "\n".join(diff)
