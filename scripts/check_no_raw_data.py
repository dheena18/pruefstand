"""Fail when raw corpora are tracked in Git (T2.1 S7, round 9 X1.3, CLAUDE.md §9).

Rules, applied to ``git ls-files``:

* a tracked file larger than 1 MB fails (``uv.lock`` and ``pnpm-lock.yaml`` are exempt);
* a tracked ``*.xml.zip``, ``*.parquet`` or ``*.arrow`` fails unless it matches ``ALLOWLIST``;
* any tracked path with a ``memerag`` component fails, allowlist or not (MEMERAG is download-only).

Extending ``ALLOWLIST`` is an interface change (decision line + T2.1 prompt), never a quiet edit.
Prints ``OK`` and exits 0, or one line per violation and exits 1.
"""

import argparse
import re
import subprocess
from collections.abc import Sequence
from functools import cache
from pathlib import Path

ALLOWLIST: tuple[str, ...] = (
    "results/**",
    "experiments/**/results/**",
    "apps/dashboard/fixtures/**",
    "datasets/fixtures/**",
    "tests/**/fixtures/**",
)
MAX_BYTES = 1024 * 1024
SIZE_EXEMPT = frozenset({"uv.lock", "pnpm-lock.yaml"})
DATA_SUFFIXES = (".xml.zip", ".parquet", ".arrow")
FORBIDDEN_COMPONENT = "memerag"


@cache
def _glob_regex(pattern: str) -> re.Pattern[str]:
    """Translate an anchored glob (``**`` = any number of directories) to a regex."""
    out: list[str] = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out) + r"\Z")


def _allowlisted(rel: str) -> bool:
    # R9 X1.3: anchored at the repo root, except "tests/**/fixtures/**", which matches a
    # "tests/" path segment anywhere (e.g. packages/pruefstand/tests/fixtures/runs/).
    return any(
        _glob_regex("**/" + p if p.startswith("tests/") else p).match(rel) for p in ALLOWLIST
    )


def find_violations(root: Path, tracked: Sequence[str]) -> list[str]:
    """Return one message per violating tracked path (empty list means clean).

    Args:
        root: Repository root; paths in ``tracked`` are relative to it.
        tracked: Tracked file paths (POSIX separators).

    Returns:
        Violation messages; files that no longer exist on disk are ignored.
    """
    problems: list[str] = []
    for rel in tracked:
        path = root / rel
        if not path.is_file():
            continue
        if FORBIDDEN_COMPONENT in (part.lower() for part in Path(rel).parts):
            problems.append(f"{rel}: MEMERAG is download-only and must never be tracked")
            continue
        if path.stat().st_size > MAX_BYTES and rel not in SIZE_EXEMPT:
            problems.append(f"{rel}: larger than 1 MB")
        if rel.endswith(DATA_SUFFIXES) and not _allowlisted(rel):
            problems.append(f"{rel}: data file outside the allowlist")
    return problems


def _git_tracked(root: Path) -> list[str]:
    result = subprocess.run(  # noqa: S603  # fixed argv, no shell, no user input
        ["git", "-C", str(root), "ls-files", "-z"],  # noqa: S607  # git from PATH
        check=True,
        capture_output=True,
        text=True,
    )
    return [p for p in result.stdout.split("\0") if p]


def main(argv: Sequence[str] | None = None, *, tracked: Sequence[str] | None = None) -> int:
    """CLI entry point; ``tracked`` overrides ``git ls-files`` (tests)."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    files = _git_tracked(args.root) if tracked is None else list(tracked)
    problems = find_violations(args.root, files)
    if problems:
        print("\n".join(problems))
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
