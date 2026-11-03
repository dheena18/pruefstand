"""Checks ``comment.md`` before the ``comment`` job upserts it as the PR comment (T1.12 S5).

The comment job runs this file checked out from the base SHA, never the PR's copy. The body is only
ever passed to the GitHub API as text; the checks keep a broken or oversized report from being
posted.
"""

import sys
from collections.abc import Sequence
from pathlib import Path

MARKER = "<!-- pruefstand:pr-comment -->"
MAX_CHARS = 60_000  # GitHub rejects comments above 65 536 characters; the rest is headroom
EXIT_USAGE = 2


def check_comment(text: str) -> list[str]:
    r"""Return what is wrong with a PR comment body (an empty list means it may be posted).

    Args:
        text: The content of ``comment.md``.

    Returns:
        One message per finding.

    Examples:
        >>> check_comment("<!-- pruefstand:pr-comment -->\\n## ok\\n")
        []
        >>> check_comment("## no marker")
        ['first line must be the marker <!-- pruefstand:pr-comment -->']
    """
    findings: list[str] = []
    first = text.split("\n", 1)[0].strip()
    if first != MARKER:
        findings.append(f"first line must be the marker {MARKER}")
    if len(text) > MAX_CHARS:
        findings.append(f"comment has {len(text)} characters, the limit is {MAX_CHARS}")
    return findings


def main(argv: Sequence[str] | None = None) -> int:
    """Check the file named by the only argument.

    Args:
        argv: Arguments; defaults to ``sys.argv[1:]``.

    Returns:
        0 when the comment may be posted, 1 on findings, 2 on a usage or read error.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        sys.stderr.write("usage: check_comment.py <comment.md>\n")
        return EXIT_USAGE
    try:
        text = Path(args[0]).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        sys.stderr.write(f"cannot read {args[0]}: {type(exc).__name__}\n")
        return EXIT_USAGE
    findings = check_comment(text)
    for finding in findings:
        sys.stderr.write(f"comment check failed: {finding}\n")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
