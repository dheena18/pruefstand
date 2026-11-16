"""Owner-merge path matcher for ``scripts/merge_reviewed.sh``.

A PR that touches an owner-merge path (workflows, VM/sudoers files, secrets docs, Claude
settings, the merge script itself, ...) must be merged by the owner, never by the lead script.
The matcher is a pure function. The CLI reads the changed paths of the PR on stdin, NUL
separated (``git diff --name-only --no-renames -z <merge-base> <sha>``: a rename shows up as a
delete plus an add, so both sides are listed, and deletions are listed too).

Matching is done on the casefolded, normalised path; when unsure the answer is "owner path".

Exit codes of the CLI: 0 no owner path touched, 3 at least one owner path touched (paths on
stderr) or the list is empty or possibly too long to review, 64 unreadable input.
"""

import posixpath
import sys
from collections.abc import Iterable

OWNER_PREFIXES: tuple[str, ...] = (
    ".github/workflows",
    ".github/actions",
    ".claude",
    "infra/vm",
    "infra/cluster",
    "infra/gate-executor",
    "infra/gpu/pruefstand-cluster",
    "scripts/hooks",
    "scripts/lead",
)
OWNER_EXACT: frozenset[str] = frozenset(
    {
        "infra/gpu/install-cluster-wrapper.sh",
        "docs/ops/secrets.md",
        ".gitleaksignore",
        ".github/codeowners",
        ".github/dependabot.yml",
        "scripts/merge_reviewed.sh",
        "scripts/merge_paths.py",
    }
)
OWNER_NAME_PREFIXES: tuple[str, ...] = ("sudoers", ".gitleaks")
OWNER_BASENAMES: frozenset[str] = frozenset({"security.yml", "codeowners"})
# More changed files than this are not reviewed by the script (refuse, owner decides).
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
    """Return True when ``path`` is an owner-merge path (compared casefolded).

    An empty or repository-escaping path counts as owner path (refuse when unsure).

    >>> is_owner_path(".github/workflows/ci.yml"), is_owner_path("./.github/../.github/actions/a")
    (True, True)
    >>> is_owner_path(".Claude/settings.json"), is_owner_path("docs/ops/secrets.md.bak")
    (True, False)
    >>> is_owner_path("a/b/sudoers.d/50-x"), is_owner_path("x/.gitleaks.toml"), is_owner_path("..")
    (True, True, True)
    >>> is_owner_path("infra/gpu/switch-mode.sh"), is_owner_path("infra/gpu/models.yaml")
    (True, False)
    """
    norm = normalise(path).casefold()
    if norm in ("", ".", "..") or norm.startswith("../"):
        return True
    if norm in OWNER_EXACT:
        return True
    if any(norm == p or norm.startswith(p + "/") for p in OWNER_PREFIXES):
        return True
    if norm.startswith("infra/gpu/") and norm.endswith(".sh"):
        return True
    parts = norm.split("/")
    if parts[-1] in OWNER_BASENAMES:
        return True
    return any(part.startswith(OWNER_NAME_PREFIXES) for part in parts)


def owner_paths_hit(paths: Iterable[str]) -> list[str]:
    """Return the owner paths among the changed ``paths`` (renames arrive as two paths).

    >>> owner_paths_hit(["docs/b.md", "infra/vm/x.sh", "infra/vm/x.sh", "docs/c.md"])
    ['infra/vm/x.sh']
    """
    hits: list[str] = []
    for path in paths:
        if is_owner_path(path) and path not in hits:
            hits.append(path)
    return hits


def parse_nul(data: str) -> list[str]:
    r"""Split NUL-separated ``data`` into paths (a trailing NUL is allowed).

    >>> parse_nul("a\0b c\0")
    ['a', 'b c']
    """
    return [p for p in data.split("\0") if p]


def main() -> int:
    """CLI entry: read NUL-separated paths on stdin, report owner paths on stderr."""
    try:
        paths = parse_nul(sys.stdin.buffer.read().decode("utf-8"))
    except (UnicodeDecodeError, OSError) as exc:
        sys.stderr.write(f"merge_paths: bad input: {exc}\n")
        return 64
    if not paths or len(paths) >= MAX_FILES:
        sys.stderr.write("merge_paths: empty or too long a file list\n")
        return 3
    hits = owner_paths_hit(paths)
    for hit in hits:
        sys.stderr.write(f"owner path: {hit}\n")
    return 3 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
