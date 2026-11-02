"""Local bare repositories as the remote of the git-backed stores (no network, no Docker)."""

import subprocess
from pathlib import Path


def git(*args: str, cwd: Path | None = None, git_dir: Path | None = None) -> str:
    """Run ``git`` and return stdout; the identity comes from the command line, not from config."""
    base = ["git", "-c", "user.name=test", "-c", "user.email=test@invalid"]
    if git_dir is not None:
        base += ["--git-dir", str(git_dir)]
    done = subprocess.run(  # noqa: S603  (fixed argument list in a test helper)
        [*base, *args], cwd=cwd, check=True, capture_output=True, text=True
    )
    return done.stdout


def bare_repo(root: Path, name: str = "remote.git") -> Path:
    """An empty bare repository."""
    path = root / name
    path.mkdir(parents=True)
    git("init", "--bare", "--quiet", str(path))
    return path


def tree_names(bare: Path, branch: str) -> list[str]:
    """Every file path in the tip tree of ``branch``."""
    out = git("ls-tree", "-r", "--name-only", branch, git_dir=bare)
    return sorted(line for line in out.splitlines() if line)


def commit_count(bare: Path, branch: str) -> int:
    """Number of commits reachable from ``branch``."""
    return int(git("rev-list", "--count", branch, git_dir=bare).strip())


def show(bare: Path, branch: str, path: str) -> str:
    """The content of ``path`` at the tip of ``branch``."""
    return git("show", f"{branch}:{path}", git_dir=bare)


def reject_pushes(bare: Path, *, times: int | None = None) -> None:
    """Install a ``pre-receive`` hook that refuses pushes (the first ``times`` ones, or all)."""
    hook = bare / "hooks" / "pre-receive"
    counter = bare / "rejections"
    if times is None:
        body = "#!/bin/sh\necho refused >&2\nexit 1\n"
    else:
        body = (
            "#!/bin/sh\n"
            f"n=$(cat {counter} 2>/dev/null || echo 0)\n"
            f'if [ "$n" -lt {times} ]; then echo $((n + 1)) > {counter}; '
            "echo refused >&2; exit 1; fi\n"
            "exit 0\n"
        )
    hook.parent.mkdir(exist_ok=True)
    hook.write_text(body, encoding="utf-8")
    hook.chmod(0o755)
