"""Test support for the lead scripts: real git repos in temp dirs, a fake ``gh`` and a fake ``uv``.

The fakes are shell tool stand-ins on PATH (not model or target fakes, CLAUDE.md section 6):
``gh`` logs its arguments and prints a PR URL; ``uv run ruff|pytest`` run the ruff and pytest of the
test interpreter.
"""

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

LEAD = Path(__file__).resolve().parent
GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
}
FAKE_GH = """#!/usr/bin/env bash
echo "$*" >> "$FAKE_DIR/gh.log"
[ "$1 $2" = "pr create" ] && echo "https://github.com/dheena18/pruefstand/pull/1"
exit 0
"""
FAKE_GIT = f"""#!/usr/bin/env bash
echo "$*" >> "$FAKE_DIR/git.log"
exec "{shutil.which("git")}" "$@"
"""
FAKE_UV = f"""#!/usr/bin/env bash
[ "$1" = run ] && shift
tool="$1"; shift
case "$tool" in
  ruff) exec "{sys.executable}" -m ruff "$@" ;;
  pytest) exec "{sys.executable}" -m pytest -p no:cacheprovider "$@" ;;
esac
exit 9
"""
SEED = {
    "docs/decisions.md": "# Decisions\n\n| D1 | one |\n| D2 | two |\n",
    "a.py": "X = 1\n",
    "other.txt": "base\n",
}


def git(cwd: Path, *args: str) -> str:
    """Run git in ``cwd`` with a fixed identity; return stripped stdout."""
    res = subprocess.run(  # noqa: S603  # fixed argv
        ["git", *args],  # noqa: S607  # git from PATH in tests
        cwd=cwd,
        env={**os.environ, **GIT_ENV},
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return res.stdout.strip()


def _exe(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


class Lab:
    """A bare origin with ``main``, a worktree clone on a feature branch, fake gh/uv."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.bin = root / "bin"
        self.bin.mkdir()
        self.home = root / "home"
        self.home.mkdir()
        self.fake = root / "fake"
        self.fake.mkdir()
        _exe(self.bin / "gh", FAKE_GH)
        _exe(self.bin / "uv", FAKE_UV)
        _exe(self.bin / "git", FAKE_GIT)
        seed = root / "seed"
        seed.mkdir()
        git(seed, "init", "-q", "-b", "main")
        for rel, text in SEED.items():
            (seed / rel).parent.mkdir(parents=True, exist_ok=True)
            (seed / rel).write_text(text, encoding="utf-8")
        shutil.copytree(
            LEAD,
            seed / "scripts" / "lead",
            ignore=shutil.ignore_patterns("tests", "__pycache__", "*.py"),
        )
        git(seed, "add", "-A")
        git(seed, "commit", "-q", "-m", "seed")
        self.origin = root / "origin.git"
        git(root, "clone", "-q", "--bare", str(seed), str(self.origin))
        self.wt = root / "wt"
        git(root, "clone", "-q", str(self.origin), str(self.wt))
        git(self.wt, "checkout", "-q", "-b", "feat/x")
        self.other = root / "other"
        git(root, "clone", "-q", str(self.origin), str(self.other))

    def write(self, rel: str, text: str, *, where: str = "wt") -> None:
        """Write a file in the worktree (``wt``) or in the other clone that plays main's author."""
        base = self.wt if where == "wt" else self.other
        (base / rel).parent.mkdir(parents=True, exist_ok=True)
        (base / rel).write_text(text, encoding="utf-8")

    def commit(self, msg: str, *, where: str = "wt") -> None:
        """Commit everything in ``wt`` (feature branch) or push to main from the other clone."""
        base = self.wt if where == "wt" else self.other
        git(base, "add", "-A")
        git(base, "commit", "-q", "-m", msg)
        if where != "wt":
            git(base, "push", "-q", "origin", "main")

    def msg(self, name: str, text: str) -> Path:
        """Write a message or body file outside the worktree."""
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return path

    def run(
        self,
        script: str,
        *args: str,
        cwd: Path | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Run ``scripts/lead/<script>`` with the fakes first on PATH."""
        env = {
            **os.environ,
            **GIT_ENV,
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "HOME": str(self.home),
            "FAKE_DIR": str(self.fake),
            **(extra_env or {}),
        }
        return subprocess.run(  # noqa: S603  # fixed argv
            [script if Path(script).is_absolute() else str(LEAD / script), *args],
            cwd=cwd or self.root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=300,
        )

    def popen(
        self, script: str, *args: str, extra_env: dict[str, str] | None = None
    ) -> subprocess.Popen[str]:
        """Start ``scripts/lead/<script>`` without waiting (own session: signals reach only it)."""
        env = {
            **os.environ,
            **GIT_ENV,
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "HOME": str(self.home),
            "FAKE_DIR": str(self.fake),
            **(extra_env or {}),
        }
        return subprocess.Popen(  # noqa: S603  # fixed argv
            [str(LEAD / script), *args],
            cwd=self.root,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )

    def git_log(self) -> str:
        """Return the log of git calls made by the scripts (through the fake git)."""
        log = self.fake / "git.log"
        return log.read_text(encoding="utf-8") if log.exists() else ""

    def gh_log(self) -> str:
        """Return the fake gh call log."""
        log = self.fake / "gh.log"
        return log.read_text(encoding="utf-8") if log.exists() else ""

    def origin_has(self, branch: str) -> bool:
        """Return True when the bare origin has ``branch``."""
        res = subprocess.run(  # noqa: S603  # fixed argv
            ["git", "-C", str(self.origin), "rev-parse", "-q", "--verify", f"refs/heads/{branch}"],  # noqa: S607
            capture_output=True,
            check=False,
            timeout=60,
        )
        return res.returncode == 0
