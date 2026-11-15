"""Owner-merge path matcher for ``scripts/merge_reviewed.sh``.

A PR that touches an owner-merge path (workflows, VM/sudoers files, secrets docs, Claude
settings, ...) must be merged by the owner, never by the lead script. The matcher is a pure
function; the CLI reads the PR file list as JSON lines on stdin (objects with ``filename`` and
optional ``previous_filename``, the shape of
``gh api repos/<repo>/pulls/<n>/files --paginate --jq ".[]"``).

Exit codes of the CLI: 0 no owner path touched, 3 at least one owner path touched (paths on stderr),
64 unreadable input.
"""

import json
import posixpath
import sys
from collections.abc import Iterable

OWNER_PREFIXES: tuple[str, ...] = (
    ".github/workflows",
    ".github/actions",
    ".claude",
    "infra/vm",
    "infra/gpu/pruefstand-cluster",
)
OWNER_EXACT: frozenset[str] = frozenset(
    {
        "infra/gpu/install-cluster-wrapper.sh",
        "docs/ops/secrets.md",
        ".gitleaksignore",
    }
)
OWNER_NAME_PREFIXES: tuple[str, ...] = ("sudoers", ".gitleaks")
OWNER_BASENAMES: frozenset[str] = frozenset({"security.yml"})
# The pulls/files API returns at most 3000 files; a list that long may be truncated.
MAX_FILES = 3000


def normalise(path: str) -> str:
    """Return a repo-relative form of ``path`` (``..`` resolved, ``./`` and leading ``/`` stripped).

    Case is preserved. A path that escapes the repository root keeps its leading ``..`` so the
    caller can treat it as suspicious.

    >>> normalise("./infra//vm/../vm/x.sh")
    'infra/vm/x.sh'
    >>> normalise("/.claude/settings.json")
    '.claude/settings.json'
    >>> normalise("a/../../b")
    '../b'
    """
    cleaned = path.replace("\\", "/").lstrip("/")
    return posixpath.normpath(cleaned) if cleaned else ""


def is_owner_path(path: str) -> bool:
    """Return True when ``path`` is an owner-merge path (case-sensitive).

    An empty or repository-escaping path counts as owner path (refuse when unsure).

    >>> is_owner_path(".github/workflows/ci.yml"), is_owner_path("./.github/../.github/actions/a")
    (True, True)
    >>> is_owner_path(".GitHub/workflows/ci.yml"), is_owner_path("docs/ops/secrets.md.bak")
    (False, False)
    >>> is_owner_path("a/b/sudoers.d/50-x"), is_owner_path("x/.gitleaks.toml"), is_owner_path("..")
    (True, True, True)
    """
    norm = normalise(path)
    if norm in ("", ".", "..") or norm.startswith("../"):
        return True
    if norm in OWNER_EXACT:
        return True
    if any(norm == p or norm.startswith(p + "/") for p in OWNER_PREFIXES):
        return True
    parts = norm.split("/")
    if parts[-1] in OWNER_BASENAMES:
        return True
    return any(part.startswith(OWNER_NAME_PREFIXES) for part in parts)


def owner_paths_hit(files: Iterable[tuple[str, str | None]]) -> list[str]:
    """Return the owner paths among ``(filename, previous_filename)`` pairs.

    A rename counts when either side is an owner path; deletions are listed like any change.

    >>> owner_paths_hit([("docs/a.md", None), ("docs/b.md", "infra/vm/x.sh"), ("infra/vm/y", None)])
    ['infra/vm/x.sh', 'infra/vm/y']
    """
    hits: list[str] = []
    for name, previous in files:
        for candidate in (name, previous):
            if candidate is not None and is_owner_path(candidate) and candidate not in hits:
                hits.append(candidate)
    return hits


def parse_lines(lines: Iterable[str]) -> list[tuple[str, str | None]]:
    """Parse JSON-lines file records into ``(filename, previous_filename)`` pairs.

    Raises:
        ValueError: a line is not a JSON object with a string ``filename``.
    """
    out: list[tuple[str, str | None]] = []
    for line in lines:
        if not line.strip():
            continue
        obj = json.loads(line)
        if not isinstance(obj, dict) or not isinstance(obj.get("filename"), str):
            msg = "record without filename"
            raise ValueError(msg)  # noqa: TRY004  # bad JSON content, not a type misuse
        prev = obj.get("previous_filename")
        if prev is not None and not isinstance(prev, str):
            msg = "bad previous_filename"
            raise ValueError(msg)
        out.append((obj["filename"], prev))
    return out


def main() -> int:
    """CLI entry: read JSON lines on stdin, report owner paths on stderr, return the exit code."""
    try:
        files = parse_lines(sys.stdin)
    except ValueError as exc:  # json.JSONDecodeError is a ValueError
        sys.stderr.write(f"merge_paths: bad input: {exc}\n")
        return 64
    if not files or len(files) >= MAX_FILES:
        sys.stderr.write("merge_paths: empty or possibly truncated file list\n")
        return 3
    hits = owner_paths_hit(files)
    for hit in hits:
        sys.stderr.write(f"owner path: {hit}\n")
    return 3 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
