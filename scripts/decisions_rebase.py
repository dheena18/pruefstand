"""Carry a stale PR's decision rows over to the file layout (D1211).

A PR branched before D1211 appends ``| D<n> | ... |`` rows to the old ``docs/decisions.md``. This
helper does, safely and in one step, what the recipe in ``docs/decisions.md`` describes:

1. find the PR's side (``HEAD`` normally and in a merge; ``orig-head`` during ``git rebase``, where
   ``HEAD`` is the upstream side) and refuse when it cannot be determined or the rebase is
   interactive;
2. move the PR's rows into ``docs/decisions/D<n>.md`` (idempotent) and ``git add`` them;
3. 3-way merge the PR's other edits of the old page (pinned versions, prose) onto the page of the
   base ref and stage the result; a real conflict leaves markers in the page and is reported.
"""

import difflib
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from decisions_files import CONFLICT_RE, ConflictMarkerError, DecisionError
from decisions_migrate import find_rows, migrate

PAGE = "docs/decisions.md"


class PrSideError(DecisionError):
    """The PR's side of a rebase or merge cannot be determined."""


@dataclass(frozen=True)
class RebaseResult:
    """Outcome of :func:`rebase_pending`.

    Attributes:
        written: Ids of the newly written (and staged) decision files.
        conflicts: Number of conflicts of the 3-way merge of the page (0 = clean).
        diff: The PR's own non-row, non-heading edits of the old page (empty when none).
    """

    written: list[str]
    conflicts: int
    diff: str


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    cmd = ["git", "-C", str(repo), *args]
    done = subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603
    if check and done.returncode:
        msg = f"git {' '.join(args)} failed: {done.stderr.strip()}"
        raise DecisionError(msg)
    return done


def _show(repo: Path, ref: str) -> str:
    return _git(repo, "show", f"{ref}:{PAGE}").stdout


def _edited(repo: Path, folder: Path, tip: str) -> bool:
    """True when the rebase todo of ``folder`` no longer lists every commit of the original tip."""
    if not (folder / "interactive").exists():
        return False
    onto = folder / "onto"
    if not onto.is_file():
        return True
    base = _git(repo, "merge-base", tip, onto.read_text(encoding="utf-8").strip(), check=False)
    expected = _git(repo, "rev-list", "--no-merges", f"{base.stdout.strip()}..{tip}").stdout.split()
    listed: list[str] = []
    for name in ("done", "git-rebase-todo"):
        f = folder / name
        lines = f.read_text(encoding="utf-8").splitlines() if f.is_file() else []
        for ln in lines:
            parts = ln.split()
            if len(parts) >= 2 and not ln.startswith("#"):
                if parts[0] in ("drop", "d"):
                    return True
                listed.append(parts[1])
    return any(not any(sha.startswith(p) for p in listed) for sha in expected)


def pr_side(repo: Path) -> str:
    """Name the commit that holds the PR's version of the page.

    Returns:
        ``HEAD`` normally and in a merge (``MERGE_HEAD`` is main); the original tip during
        ``git rebase`` (``HEAD`` is the upstream side there).

    Raises:
        PrSideError: a rebase is running but its original tip cannot be read.
    """
    for name in ("rebase-merge", "rebase-apply"):
        out = _git(repo, "rev-parse", "--git-path", name).stdout.strip()
        folder = Path(out) if Path(out).is_absolute() else repo / out
        if folder.is_dir():
            tip = folder / "orig-head"
            if tip.is_file() and tip.read_text(encoding="utf-8").strip():
                sha = tip.read_text(encoding="utf-8").strip()
                if _edited(repo, folder, sha):
                    msg = (
                        "interactive rebase that drops or loses commits: the PR side would be the "
                        "whole original tip, not the replayed commits. Run it after the rebase "
                        "finishes, from a merge of origin/main, or use a non-interactive rebase"
                    )
                    raise PrSideError(msg)
                return sha
            msg = f"rebase in progress but {name}/orig-head is missing; PR side unknown"
            raise PrSideError(msg)
    return "HEAD"


def stage_files(directory: Path, paths: list[Path]) -> bool:
    """``git add`` files inside a work tree; ``False`` when ``directory`` is not in one."""
    if not paths or _git(directory, "rev-parse", "--show-toplevel", check=False).returncode:
        return False
    _git(directory, "add", "--", *[str(p) for p in paths])
    return True


def _non_rows(text: str) -> list[str]:
    drop = {r.line_no for r in find_rows(text)}
    return [ln for i, ln in enumerate(text.split("\n")) if i not in drop]


def _merge_page(repo: Path, mine: str, old: str, theirs: str) -> tuple[str, int]:
    with tempfile.TemporaryDirectory() as tmp:
        files = {n: Path(tmp) / n for n in ("ours", "base", "theirs")}
        for name, text in (("ours", mine), ("base", old), ("theirs", theirs)):
            files[name].write_text(text, encoding="utf-8")
        labels = ["-L", "PR", "-L", "merge-base", "-L", "base-ref"]
        done = _git(repo, "merge-file", "-p", *labels, *[str(files[n]) for n in files], check=False)
    if done.returncode < 0 or done.returncode >= 128:
        msg = f"git merge-file failed: {done.stderr.strip()}"
        raise DecisionError(msg)
    return done.stdout, done.returncode


def rebase_pending(repo: Path, base_ref: str = "origin/main") -> RebaseResult:
    """Move the PR's rows into files and bring the page to ``base_ref``'s version.

    Args:
        repo: Repository root with the PR branch checked out (clean, in a merge, or in a rebase).
        base_ref: The ref that holds the new layout (``origin/main``).

    Returns:
        The staged files, the number of conflicts of the page merge and the PR's own page edits.

    Raises:
        ConflictMarkerError: the PR's copy holds conflict markers (nothing is changed).
        PrSideError: the PR's side of a running rebase cannot be determined (nothing changed).
        DecisionError: on an id clash, a duplicate id or a git failure (nothing is changed).
    """
    side = pr_side(repo)
    mine = _show(repo, side)
    if CONFLICT_RE.search(mine):
        msg = f"{side}:docs/decisions.md contains conflict markers"
        raise ConflictMarkerError(msg)
    base = _git(repo, "merge-base", side, base_ref).stdout.strip()
    old = _show(repo, base)
    theirs = _show(repo, base_ref)
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "decisions.md"
        copy.write_text(mine, encoding="utf-8")
        written = migrate(copy, repo / "docs" / "decisions")
        mine_rows_out = copy.read_text(encoding="utf-8")
    old_rows_out = "\n".join(_non_rows(old))
    merged, conflicts = _merge_page(repo, mine_rows_out, old_rows_out, theirs)
    (repo / PAGE).write_text(merged, encoding="utf-8")
    stage_files(repo, [repo / "docs" / "decisions" / f"{i}.md" for i in written])
    if not conflicts:
        _git(repo, "add", "--", PAGE)
    plain = list(
        difflib.unified_diff(
            [x for x in old_rows_out.split("\n") if not x.startswith("#")],
            [x for x in mine_rows_out.split("\n") if not x.startswith("#")],
            "merge-base",
            "PR",
            lineterm="",
            n=0,
        )
    )
    return RebaseResult(written, conflicts, "\n".join(plain))
