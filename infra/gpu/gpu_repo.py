"""A temp git repo with a local bare ``origin`` holding the files the installer and the deploy use (T3.1a).

The installer and the deploy only act on a tree equal to ``origin/main`` (M3); tests that run them need a
clean checkout, which the real working tree of a task branch never is.
"""

import getpass
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from gpu_testkit import CLUSTER_DIR, GPU_DIR, link_tools, python_stub, run_script
from vm_testkit import Result, Stubs

GPU_FILES = (
    "pruefstand-cluster", "install-cluster-wrapper.sh", "deploy-cluster-bin.sh",
    "gpu_catalogue.py", "models.yaml", "lib/git_verify.sh", "lib/gpu_common.sh",
    "lib/cluster_ssh.sh",
)  # fmt: skip


@dataclass
class Repo:
    root: Path
    stubs: Stubs
    dest: Path
    remote: Path

    def git(self, *args: str) -> str:
        env = {**os.environ, "HOME": str(self.root.parent), "GIT_CONFIG_GLOBAL": "/dev/null"}
        env.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.org")
        env.update(GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.org")
        out = subprocess.run(  # noqa: S603
            ["git", *args],
            cwd=self.root,
            env=env,
            capture_output=True,
            text=True,
            check=True,  # noqa: S607
        )
        return out.stdout.strip()

    def run(self, script: str, *args: str, **env: str) -> Result:
        path = self.root / "infra" / "gpu" / script
        base = {"PRUEFSTAND_SERVICE_USER": getpass.getuser(), "PRUEFSTAND_PYTHON": "python3"}
        return run_script(path, *args, stubs=self.stubs, env={**base, **env})


def make_repo(tmp_path: Path, stubs: Stubs) -> Repo:
    """Create the repo, push it to a bare origin and stub the tools the scripts need."""
    root = tmp_path / "work" / "repo"
    (root / "infra" / "gpu" / "lib").mkdir(parents=True)
    (root / "infra" / "cluster").mkdir(parents=True)
    for name in GPU_FILES:
        shutil.copy(GPU_DIR / name, root / "infra" / "gpu" / name)
    for src in [*CLUSTER_DIR.glob("*.sh"), CLUSTER_DIR / "cluster.env.template"]:
        shutil.copy(src, root / "infra" / "cluster" / src.name)
    remote = tmp_path / "origin.git"
    result = Repo(root, stubs, tmp_path / "dest", remote)
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)  # noqa: S607
    result.git("init", "-q", "-b", "main")
    result.git("add", "-A")
    result.git("commit", "-q", "-m", "base")
    result.git("remote", "add", "origin", str(remote))
    result.git("push", "-q", "origin", "main")
    link_tools(stubs, "git", "diff", "install", "cat", "cp", "mv", "mkdir", "chmod", "sort")
    python_stub(stubs)
    stubs.add("visudo", [("-c -f *", "parsed OK", 0)])
    return result
