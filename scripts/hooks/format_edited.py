"""Claude Code PostToolUse hook: format and fix the Python file that was just edited (T0.1 S13).

Reads the hook JSON from stdin, takes ``tool_input.file_path`` and runs ``ruff format`` and
``ruff check --fix`` on it, only for a ``.py`` file inside the repository. Always exits 0 and
prints problems instead of failing the session.
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import TextIO

REPO_ROOT = Path(__file__).resolve().parents[2]
RUFF_TIMEOUT_S = 60


def _target(stdin: TextIO, root: Path) -> Path | None:
    try:
        payload = json.load(stdin)
        file_path = Path(payload["tool_input"]["file_path"]).resolve()
    except (ValueError, KeyError, TypeError) as exc:
        print(f"format_edited: ignoring hook input ({exc!r})")
        return None
    if file_path.suffix != ".py" or not file_path.is_file():
        return None
    if not file_path.is_relative_to(root.resolve()):
        return None
    return file_path


def main(stdin: TextIO | None = None, *, root: Path = REPO_ROOT) -> int:
    """Format the edited file; return 0 in every case."""
    target = _target(stdin or sys.stdin, root)
    if target is None:
        return 0
    for args in (["format"], ["check", "--fix"]):
        try:
            done = subprocess.run(  # noqa: S603
                [sys.executable, "-m", "ruff", *args, str(target)],
                cwd=root, capture_output=True, text=True, timeout=RUFF_TIMEOUT_S, check=False,
            )  # fmt: skip
        except (OSError, subprocess.TimeoutExpired) as exc:
            print(f"format_edited: ruff {args[0]} failed to run: {exc!r}")
            continue
        if done.returncode != 0:
            print(f"format_edited: ruff {args[0]} reported:\n{done.stdout}{done.stderr}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
