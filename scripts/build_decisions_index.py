"""Build, check and migrate the decision files (D1211).

Usage::

    uv run python scripts/build_decisions_index.py             # write docs/decisions-log.md
    uv run python scripts/build_decisions_index.py --check     # validate (tests, make check)
    uv run python scripts/build_decisions_index.py --stdout     # print the log
    uv run python scripts/build_decisions_index.py --migrate-pending
        # move rows a stale branch appended to docs/decisions.md into docs/decisions/D<n>.md
    uv run python scripts/build_decisions_index.py --rebase-pending [--base-ref origin/main]
        # stale PR branch: do the whole recipe of docs/decisions.md in one step

The log ``docs/decisions-log.md`` is git-ignored: it is rebuilt by ``mkdocs`` (hook in
``scripts/mkdocs_hooks.py``), so two PRs that add two decisions never conflict.
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from decisions_files import (
    CONFLICT_RE,
    ConflictMarkerError,
    DecisionError,
    load_dir,
    render_log,
    validate,
)
from decisions_migrate import find_rows, migrate
from decisions_rebase import rebase_pending

REPO = Path(__file__).resolve().parents[1]
DEFAULT_DIR = REPO / "docs" / "decisions"
DEFAULT_MD = REPO / "docs" / "decisions.md"
DEFAULT_LOG = REPO / "docs" / "decisions-log.md"


def check(directory: Path, decisions_md: Path) -> list[str]:
    """Validate the layout.

    Args:
        directory: ``docs/decisions``.
        decisions_md: The hand-written ``docs/decisions.md``.

    Returns:
        Problems: file/id rules (see ``decisions_files.validate``) plus every ``| D<n> |`` row
        still sitting in ``decisions.md`` (it must be a file; run ``--migrate-pending``).
    """
    problems = validate(directory)
    if decisions_md.exists():
        text = decisions_md.read_text(encoding="utf-8")
        if CONFLICT_RE.search(text):
            problems.append(f"{decisions_md.name}: contains git conflict markers")
        pending = find_rows(text)
        problems += [
            f"{decisions_md.name}: row {r.decision.id} must be a file "
            f"{directory.name}/{r.decision.id}.md (run: scripts/build_decisions_index.py "
            "--migrate-pending)"
            for r in pending
        ]
    return problems


def build_log(directory: Path = DEFAULT_DIR) -> str:
    """Render the generated log from the decision files.

    Raises:
        DecisionError: when the directory is invalid.
    """
    problems = validate(directory)
    if problems:
        raise DecisionError("; ".join(problems))
    decisions, _ = load_dir(directory)
    return render_log(decisions)


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0] if __doc__ else "")
    ap.add_argument("--check", action="store_true", help="validate, write nothing")
    ap.add_argument("--stdout", action="store_true", help="print the log instead of writing it")
    ap.add_argument("--migrate-pending", action="store_true", help="move old-style rows to files")
    ap.add_argument(
        "--rebase-pending",
        action="store_true",
        help="stale PR branch: rows to files, page of --base-ref, show other edits",
    )
    ap.add_argument("--base-ref", default="origin/main")
    ap.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    ap.add_argument("--decisions-md", type=Path, default=DEFAULT_MD)
    ap.add_argument("--out", type=Path, default=DEFAULT_LOG)
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point.

    Returns:
        0 on success, 1 on problems, 2 on git conflict markers (printed to stderr; nothing is
        written in that case).
    """
    args = _parser().parse_args(argv)
    try:
        if args.rebase_pending:
            written, diff = rebase_pending(REPO, args.base_ref)
            print(f"wrote {len(written)} file(s): {', '.join(written) or '-'}")
            if diff:
                print("Other edits of the PR on the old page, re-apply by hand:\n" + diff)
        if args.migrate_pending:
            moved = migrate(args.decisions_md, args.dir)
            print(f"wrote {len(moved)} file(s): {', '.join(moved) or '-'}")
        problems = check(args.dir, args.decisions_md)
        if problems:
            print("\n".join(problems), file=sys.stderr)
            return 1
        if args.check:
            return 0
        log = build_log(args.dir)
    except ConflictMarkerError as exc:
        print(f"decisions: {exc}", file=sys.stderr)
        return 2
    except DecisionError as exc:
        print(f"decisions: {exc}", file=sys.stderr)
        return 1
    if args.stdout:
        sys.stdout.write(log)
    elif not args.migrate_pending:
        args.out.write_text(log, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
