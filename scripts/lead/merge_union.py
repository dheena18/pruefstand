"""Union-merge helper of ``resolve_merge.sh`` for append-only files (D1230).

Append-only files (``docs/decisions.md``, ``tasks/TASKS.md``, ...) keep BOTH sides of a merge
conflict: the conflicting hunk becomes ours + theirs (identical lines once; decision rows ordered
by D-number). Anything else is left to a human. The ``dupes`` check refuses D-numbers that occur
more often than on the reference ref.

Subcommands: ``allowed FILE...`` (exit 1 when one is not append-only), ``resolve FILE...`` (rewrite
the conflict markers away, exit 1 when a file has none or is not allowed), ``dupes REF FILE...``
(exit 1 on a D-number that occurs more often than in ``REF:FILE``).
"""

import re
import subprocess
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

APPEND_ONLY: frozenset[str] = frozenset(
    {
        "docs/decisions.md",
        "tasks/TASKS.md",
        "docs/engineering/test-matrix.md",
        "docs/engineering/gpu-cluster.md",
        "docs/architecture/sequences.md",
        "docs/architecture/interfaces.md",
        "docs/ops/secrets.md",
        ".env.example",
        "DATA_LICENSES.md",
        ".gitleaks.toml",
    }
)
APPEND_ONLY_PREFIXES: tuple[str, ...] = ("docs/decisions/",)
ROW = re.compile(r"^\| D(\d+) \|")
LAST = 10**9


def is_append_only(path: str) -> bool:
    """Return True when ``path`` may be resolved by keeping both sides.

    >>> is_append_only("docs/decisions.md"), is_append_only("docs/decisions/d1200.md")
    (True, True)
    >>> is_append_only("scripts/x.py")
    False
    """
    return path in APPEND_ONLY or path.startswith(APPEND_ONLY_PREFIXES)


def _row_key(line: str) -> int:
    match = ROW.match(line)
    return int(match.group(1)) if match else LAST


def _merge_block(ours: list[str], theirs: list[str], *, rows: bool) -> list[str]:
    lines = [ln for ln in ours + theirs if ln.strip()] if rows else ours + theirs
    seen: set[str] = set()
    merged: list[str] = []
    for line in lines:
        if line.strip() and line in seen:
            continue
        seen.add(line)
        merged.append(line)
    return sorted(merged, key=_row_key) if rows else merged


def resolve_text(text: str, *, rows: bool) -> tuple[str, int]:
    r"""Replace every conflict block by both sides; return the new text and the block count.

    ``rows`` drops blank lines inside a block and orders ``| D<n> |`` rows by number.

    >>> src = "a\n<<<<<<< HEAD\n| D2 | x |\n=======\n| D1 | y |\n>>>>>>> main\nb\n"
    >>> resolve_text(src, rows=True)
    ('a\n| D1 | y |\n| D2 | x |\nb\n', 1)
    """
    out: list[str] = []
    ours: list[str] = []
    theirs: list[str] = []
    mode = ""
    blocks = 0
    for line in text.split("\n"):
        if line.startswith("<<<<<<<") and not mode:
            mode, ours, theirs = "o", [], []
        elif line.startswith("|||||||") and mode == "o":
            mode = "b"  # diff3 base section: dropped
        elif line.startswith("=======") and mode in ("o", "b"):
            mode = "t"
        elif line.startswith(">>>>>>>") and mode == "t":
            out.extend(_merge_block(ours, theirs, rows=rows))
            mode = ""
            blocks += 1
        elif mode == "o":
            ours.append(line)
        elif mode == "t":
            theirs.append(line)
        elif mode != "b":
            out.append(line)
    if mode:
        msg = "unterminated conflict block"
        raise ValueError(msg)
    return "\n".join(out), blocks


def decision_counts(text: str) -> Counter[int]:
    r"""Count the ``| D<n> |`` rows per number.

    >>> decision_counts("| D1 | a |\n| D1 | b |\n| D2 | c |\n")
    Counter({1: 2, 2: 1})
    """
    return Counter(int(m.group(1)) for line in text.split("\n") if (m := ROW.match(line)))


def excess_duplicates(merged: str, reference: str) -> list[int]:
    r"""Return the D-numbers occurring in ``merged`` more than once and more than in ``reference``.

    >>> excess_duplicates("| D5 | a |\n| D5 | b |\n", "| D5 | a |\n")
    [5]
    >>> excess_duplicates("| D5 | a |\n| D5 | b |\n", "| D5 | a |\n| D5 | b |\n")
    []
    """
    ref = decision_counts(reference)
    return sorted(n for n, c in decision_counts(merged).items() if c > 1 and c > ref[n])


def _git_show(ref: str, path: str) -> str:
    res = subprocess.run(  # noqa: S603  # fixed argv
        ["git", "show", f"{ref}:{path}"],  # noqa: S607  # git from PATH
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    return res.stdout if res.returncode == 0 else ""


def _cmd_allowed(files: Sequence[str]) -> int:
    bad = [f for f in files if not is_append_only(f)]
    for path in bad:
        sys.stderr.write(f"NEEDS MANUAL: {path}\n")
    return 1 if bad else 0


def _cmd_resolve(files: Sequence[str]) -> int:
    if _cmd_allowed(files):
        return 1
    for path in files:
        text = Path(path).read_text(encoding="utf-8")
        try:
            new, blocks = resolve_text(text, rows=path.endswith("decisions.md"))
        except ValueError as exc:
            sys.stderr.write(f"NEEDS MANUAL: {path}: {exc}\n")
            return 1
        if blocks == 0:
            sys.stderr.write(f"NEEDS MANUAL: {path}: no conflict markers (modify/delete?)\n")
            return 1
        Path(path).write_text(new, encoding="utf-8")
        sys.stdout.write(f"resolved {path} ({blocks} block(s))\n")
    return 0


def _cmd_dupes(ref: str, files: Sequence[str]) -> int:
    bad = 0
    for path in files:
        merged = Path(path).read_text(encoding="utf-8")
        for number in excess_duplicates(merged, _git_show(ref, path)):
            sys.stderr.write(f"DUPLICATE D-number D{number} in {path}: renumber one of the rows\n")
            bad = 1
    return bad


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry (see the module docstring)."""
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) >= 2 and args[0] == "allowed":
        return _cmd_allowed(args[1:])
    if len(args) >= 2 and args[0] == "resolve":
        return _cmd_resolve(args[1:])
    if len(args) >= 3 and args[0] == "dupes":
        return _cmd_dupes(args[1], args[2:])
    sys.stderr.write("usage: merge_union.py allowed|resolve FILE... | dupes REF FILE...\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
