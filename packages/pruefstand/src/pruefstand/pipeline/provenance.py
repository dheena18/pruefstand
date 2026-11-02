"""Where a run came from: git sha and ref, pull request number (T1.10 S2 step 6).

Every value is validated; anything malformed is dropped (None), never passed on to ``run.json``.
"""

import json
import re
import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from pruefstand.pipeline._files import read_regular

_SHA = re.compile(r"[0-9a-f]{7,64}")
_REF = re.compile(r"[A-Za-z0-9._/@+-]{1,255}")
_MAX_EVENT_BYTES = 2 * 1024 * 1024
_MAX_PR_NUMBER = 10**9
_GIT_TIMEOUT_S = 5.0


@dataclass(frozen=True)
class Provenance:
    """Git and pull request facts of a run; each field is None when unknown."""

    git_sha: str | None
    git_ref: str | None
    pr_number: int | None


def _git(*args: str) -> str | None:
    exe = shutil.which("git")
    if exe is None:
        return None
    try:
        done = subprocess.run(  # noqa: S603  (fixed argument list, no shell, timeout)
            [exe, *args], capture_output=True, text=True, timeout=_GIT_TIMEOUT_S, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def _valid_or_git(value: str | None, pattern: re.Pattern[str], *git_args: str) -> str | None:
    """Return ``value`` if it matches ``pattern``, else the output of ``git <args>`` if it does."""
    if value and pattern.fullmatch(value):
        return value
    found = _git(*git_args)
    return found if found and found != "HEAD" and pattern.fullmatch(found) else None


def _event_text(path: Path) -> bytes | None:
    try:
        raw = read_regular(path, _MAX_EVENT_BYTES)
    except OSError:
        return None
    return raw if len(raw) <= _MAX_EVENT_BYTES else None


def _pr_number(env: Mapping[str, str]) -> int | None:
    named = env.get("GITHUB_EVENT_PATH")
    raw = _event_text(Path(named)) if named else None
    if raw is None:
        return None
    try:
        event = json.loads(raw)
    except ValueError:
        return None
    pull = event.get("pull_request") if isinstance(event, dict) else None
    number = pull.get("number") if isinstance(pull, dict) else None
    if isinstance(number, int) and not isinstance(number, bool) and 0 < number < _MAX_PR_NUMBER:
        return number
    return None


def read_provenance(env: Mapping[str, str]) -> Provenance:
    """Collect git sha, git ref and PR number.

    The sha and ref come from ``GITHUB_SHA`` / ``GITHUB_REF`` when they look right, else from
    ``git rev-parse``. The PR number comes from the event file named by ``GITHUB_EVENT_PATH``
    (read with a 2 MB cap); a missing, oversized or malformed file gives None.

    Args:
        env: The environment.

    Returns:
        The facts; unknown or malformed values are None.
    """
    return Provenance(
        _valid_or_git(env.get("GITHUB_SHA"), _SHA, "rev-parse", "HEAD"),
        _valid_or_git(env.get("GITHUB_REF"), _REF, "rev-parse", "--abbrev-ref", "HEAD"),
        _pr_number(env),
    )
