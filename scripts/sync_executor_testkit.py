"""Sandbox of the ``sync_executor.sh`` tests (T6.2a S10, D1085): real git, a stubbed ``gh``."""

import os
import stat
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "sync_executor.sh"
TAG = "executor-20261115"


def git(cwd: Path, *args: str) -> str:
    """Run git in ``cwd``; return its stdout (raises on failure)."""
    done = subprocess.run(  # noqa: S603 - fixed argv
        ["git", *args],  # noqa: S607 - git from PATH
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return done.stdout.strip()


def write(root: Path, rel: str, text: str) -> None:
    """Write ``text`` to ``root/rel``, creating parent directories."""
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def init(path: Path) -> None:
    """A fresh repo on ``main`` with a test identity."""
    path.mkdir(parents=True)
    git(path, "init", "-q", "-b", "main")
    git(path, "config", "user.email", "test@example.invalid")
    git(path, "config", "user.name", "test")


class Sandbox:
    """A public repo with executor files, a bare private repo and a logging ``gh`` stub."""

    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.public = tmp / "public"
        init(self.public)
        for rel, text in {
            "infra/gate-executor/orchestrator/gate_orchestrator/x.py": "X = 1\n",
            "infra/gate-executor/llm-proxy/llm_proxy.py": "P = 1\n",
            "infra/gate-executor/host/job_started.sh": "#!/usr/bin/env bash\n",
            "infra/gate-executor/workflows/gate-executor.yml": "name: gate-executor\n",
            "infra/gate-executor/workflows/README.md": "source of the private workflows\n",
            "infra/gate-executor/private-repo-template/README.md": "# pruefstand-gate\n",
            "infra/gate-executor/private-repo-template/.gitignore": "*.partial\n",
            "apps/rag-demo/not_synced.py": "N = 1\n",
        }.items():
            write(self.public, rel, text)
        hook = self.public / "infra/gate-executor/host/job_started.sh"
        hook.chmod(hook.stat().st_mode | stat.S_IEXEC)  # an executable host script (100755)
        git(self.public, "add", "-A")
        git(self.public, "commit", "-q", "-m", "public")
        self.private = tmp / "private.git"
        seed = tmp / "seed"
        init(seed)
        write(seed, "infra/gate-executor/orchestrator/old.py", "OLD = 1\n")
        write(seed, "canaries/heldout/README.md", "private\n")
        write(seed, ".github/workflows/retired.yml", "name: retired\n")
        git(seed, "add", "-A")
        git(seed, "commit", "-q", "-m", "seed")
        git(tmp, "clone", "-q", "--bare", str(seed), str(self.private))
        self.bin = tmp / "bin"
        self.bin.mkdir()
        gh = self.bin / "gh"
        gh.write_text(f'#!/bin/sh\necho "$@" >> {tmp / "gh.log"}\n', encoding="utf-8")
        gh.chmod(gh.stat().st_mode | stat.S_IEXEC)

    def tag(self, name: str = TAG, *, annotated: bool = True) -> None:
        """Tag the public repo (annotated by default)."""
        args = ["tag", "-a", name, "-m", "executor sync"] if annotated else ["tag", name]
        git(self.public, *args)

    def run(self, *args: str, **extra_env: str) -> subprocess.CompletedProcess[str]:
        """Run sync_executor.sh in the public repo with the sandbox env."""
        env = {
            **os.environ,
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "PRIVATE_REMOTE": str(self.private),
            "MAIN_REF": "main",
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "test@example.invalid",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "test@example.invalid",
            **extra_env,
        }
        return subprocess.run(  # noqa: S603 - fixed argv
            ["bash", str(SCRIPT), *args], cwd=self.public, env=env, capture_output=True, text=True,  # noqa: S607 - bash from PATH
            check=False,
        )  # fmt: skip

    def private_tree(self, ref: str) -> dict[str, str]:
        """Path to content of every file of ``ref`` in the private repo."""
        names = git(self.private, "ls-tree", "-r", "--name-only", ref).splitlines()
        return {n: git(self.private, "show", f"{ref}:{n}") for n in names}


def empty_remote(box: Sandbox) -> Path:
    """An empty bare private repo (for ``--init``)."""
    empty = box.tmp / "empty.git"
    git(box.tmp, "init", "-q", "--bare", "-b", "main", str(empty))
    return empty
