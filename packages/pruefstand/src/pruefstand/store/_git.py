"""A small ``git`` runner: list arguments, no shell, timeouts, the token only via ``GIT_ASKPASS``.

Used by the git-backed baseline store and the dashboard-data push. The token is read from an
environment variable *by name*; it never appears on a command line, in a URL, in a log or in an
exception message.
"""

import os
import re
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path
from types import TracebackType
from typing import Self

from pruefstand.core.errors import StoreError

_REPO = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*")
_ASKPASS = """#!/bin/sh
case "$1" in
  Username*) printf '%s\\n' x-access-token ;;
  *) printf '%s\\n' "$PRUEFSTAND_ASKPASS_TOKEN" ;;
esac
"""
_PASS = frozenset(
    {
        *("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "SSL_CERT_FILE", "SSL_CERT_DIR"),
        *("CURL_CA_BUNDLE", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ALL_PROXY"),
        *("http_proxy", "https_proxy", "no_proxy", "all_proxy"),
    }
)
_TOKEN_VAR = "PRUEFSTAND_ASKPASS_TOKEN"  # noqa: S105  (the NAME of a variable, not a secret)
_IDENTITY = (
    "-c",
    "user.name=pruefstand",
    "-c",
    "user.email=noreply@invalid",
    "-c",
    "commit.gpgsign=false",
)


def valid_repo(repo: str) -> str:
    """Return ``repo`` if it is ``owner/name`` with safe characters.

    Raises:
        StoreError: Anything else.
    """
    if _REPO.fullmatch(repo) is None or ".." in repo:
        msg = f"invalid repo {repo[:40]!r}: expected 'owner/name'"
        raise StoreError(msg)
    return repo


def remote_url(repo: str, remote: str | None = None) -> str:
    """The git URL of ``repo`` on GitHub, or ``remote`` (a local path or URL) when given.

    Args:
        repo: ``owner/name``.
        remote: Optional override (tests use a local bare repository).

    Returns:
        ``https://github.com/<repo>.git``, a ``file://`` URL for an existing local path, or
        ``remote`` itself.

    Raises:
        StoreError: ``repo`` is not ``owner/name``, or ``remote`` looks like an option.
    """
    valid_repo(repo)
    if remote is None:
        return f"https://github.com/{repo}.git"
    if remote.startswith("-"):
        msg = "invalid remote: must not start with '-'"
        raise StoreError(msg)
    local = Path(remote)
    return local.resolve().as_uri() if local.exists() else remote


class Git:
    """Runs ``git`` inside a session (a context manager that owns the askpass helper).

    Args:
        token_env: Name of the environment variable that holds the access token, or None. When
            the variable is empty or unset git runs without credentials.
        timeout_s: Per-command timeout.
    """

    def __init__(self, token_env: str | None = None, *, timeout_s: float = 120.0) -> None:
        self._token_env = token_env
        self._timeout_s = timeout_s
        self._dir: Path | None = None
        self._env: dict[str, str] | None = None

    def __enter__(self) -> Self:
        self._dir = Path(tempfile.mkdtemp(prefix="pruefstand-git-"))
        self._dir.chmod(stat.S_IRWXU)
        env = {k: v for k, v in os.environ.items() if k in _PASS}  # no other secret reaches git
        token = os.environ.get(self._token_env, "") if self._token_env else ""
        env.update(
            {
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": os.devnull,
            }
        )
        if token:
            script = self._dir / "askpass.sh"
            script.write_text(_ASKPASS, encoding="utf-8")
            script.chmod(stat.S_IRWXU)
            env["GIT_ASKPASS"] = str(script)
            env[_TOKEN_VAR] = token
        self._env = env
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._dir is not None:
            shutil.rmtree(self._dir, ignore_errors=True)
        self._dir = None
        self._env = None

    def environment(self) -> dict[str, str]:
        """The environment git runs with (open session only)."""
        if self._env is None:
            msg = "git must run inside a 'with Git(...)' session"
            raise StoreError(msg)
        return dict(self._env)

    def run(self, *args: str, cwd: Path | None = None, identity: bool = False) -> str:
        """Run ``git <args>`` and return stdout.

        Args:
            *args: Arguments (a list, never a shell string).
            cwd: Working directory.
            identity: Add the committer identity options (for ``commit``).

        Raises:
            StoreError: Non-zero exit or timeout; the message names the git command and the
                scrubbed first stderr line, never the token.
        """
        env = self.environment()
        argv = ["git", *(_IDENTITY if identity else ()), *args]
        name = _command(args)
        try:
            done = subprocess.run(  # noqa: S603  (fixed program, list arguments, no shell)
                argv, cwd=cwd, env=env, capture_output=True, text=True, check=False,
                timeout=self._timeout_s, shell=False,
            )  # fmt: skip
        except subprocess.TimeoutExpired as exc:
            msg = f"git {name} timed out after {self._timeout_s:g} s"
            raise StoreError(msg) from exc
        except OSError as exc:
            msg = f"cannot run git {name}: {type(exc).__name__}"
            raise StoreError(msg) from exc
        if done.returncode != 0:
            detail = _scrub(done.stderr, env.get(_TOKEN_VAR))
            msg = f"git {name} failed (exit {done.returncode}): {detail}"
            raise StoreError(msg)
        return done.stdout


def _command(args: tuple[str, ...]) -> str:
    skip = False
    for arg in args:
        if skip:
            skip = False
        elif arg == "-c":
            skip = True
        elif not arg.startswith("-"):
            return arg
    return "command"


def _scrub(text: str, token: str | None) -> str:
    lines = [line for line in text.strip().splitlines() if line.strip()]
    first = lines[0] if lines else "no message"
    if token:
        first = first.replace(token, "***")
    return first[:300]
