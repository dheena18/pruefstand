"""Guard for the release PR's `uv lock` commit (T9.1a S1b, R9 X2.9, D159).

After release-please bumps the workspace members' versions, `release-please.yml` runs `uv lock` and
may commit `uv.lock` to the release PR. That commit must change only the `version = "..."` lines of
the workspace members and the virtual root (the release exemption of ci-cd.md §5 and
``gate_router_regex.RELEASE_RULES``);
anything else (a dependency's version, a hash, a new package) is dependency drift and belongs in a
normal, gated PR.

Usage: ``git diff -- uv.lock | python scripts/ci/check_release_lock_diff.py``; exit 0 ok, 1 refused.
"""

import re
import sys
from collections.abc import Iterable

# the workspace members and the virtual workspace root (its version follows the release, D1292)
MEMBERS: frozenset[str] = frozenset({"pruefstand", "rag-demo", "pruefstand-workspace"})
_NAME = re.compile(r'^name = "([^"]+)"$')
_VERSION = re.compile(r'^version = "[^"]+"$')


def problems(diff: str, members: Iterable[str] = MEMBERS) -> list[str]:
    r"""Changed lines of a ``uv.lock`` diff that are not a member's ``version`` line.

    The package a line belongs to is the last ``name = "..."`` line seen in the diff (``git diff``
    shows it as context right above the ``version`` line it owns).

    Examples:
        >>> diff = ' name = "pruefstand"\n-version = "0.1.0"\n+version = "0.2.0"\n'
        >>> problems(diff)
        []
        >>> problems(' name = "anyio"\n-version = "4.0"\n+version = "4.1"\n')
        ['anyio: -version = "4.0"', 'anyio: +version = "4.1"']
    """
    allowed = set(members)
    current = ""
    found: list[str] = []
    for raw in diff.splitlines():
        if raw.startswith(("+++", "---", "@@", "diff ", "index ")):
            continue
        body = raw[1:]
        name = _NAME.match(body)
        if name:
            current = name.group(1)
        if raw[:1] not in "+-":
            continue
        if not (_VERSION.match(body) and current in allowed):
            found.append(f"{current or '?'}: {raw}")
    return found


def main(argv: list[str]) -> int:
    """Read the diff from a file argument or stdin; print the refused lines."""
    diff = open(argv[0], encoding="utf-8").read() if argv else sys.stdin.read()  # noqa: PTH123, SIM115
    found = problems(diff)
    for line in found:
        print(f"uv.lock: not a release version line: {line}", file=sys.stderr)
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
