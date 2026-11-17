"""sync_executor.sh: file modes and the printed VM step (T6.2a S10)."""

from pathlib import Path

import pytest
from sync_executor_testkit import TAG, Sandbox, empty_remote, git


@pytest.fixture
def box(tmp_path: Path) -> Sandbox:
    return Sandbox(tmp_path)


VM_STEP = "sudo -u pruefstand git -C /home/pruefstand/pruefstand-gate pull --ff-only"


def test_modes_come_from_the_public_tree_even_with_filemode_false(box: Sandbox) -> None:
    # Windows Git Bash clones with core.fileMode=false, so a plain `git add` stores every new
    # file as 100644; the executable host scripts must stay 100755 in the private repo.
    # Command-level config wins over the repo-local value a fresh clone probes on Linux.
    box.tag()
    res = box.run(
        TAG, GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="core.fileMode", GIT_CONFIG_VALUE_0="false"
    )
    assert res.returncode == 0, res.stderr
    ref = f"sync/{TAG}"
    hook = git(box.private, "ls-tree", ref, "infra/gate-executor/host/job_started.sh")
    assert hook.startswith("100755 ")
    plain = git(box.private, "ls-tree", ref, "infra/gate-executor/llm-proxy/llm_proxy.py")
    assert plain.startswith("100644 ")


@pytest.mark.parametrize("mode", ["pr", "dry-run", "nothing", "init"])
def test_the_printed_instructions_end_with_the_vm_pull(box: Sandbox, mode: str) -> None:
    if mode == "init":
        box.private = empty_remote(box)
    box.tag()
    if mode == "nothing":
        assert box.run(TAG).returncode == 0
        git(box.tmp, "--git-dir", str(box.private), "branch", "-f", "main", f"sync/{TAG}")
    args = {"pr": (), "dry-run": ("--dry-run",), "nothing": (), "init": ("--init",)}[mode]
    res = box.run(TAG, *args)
    assert res.returncode == 0, res.stderr
    assert res.stdout.rstrip().splitlines()[-1].endswith(VM_STEP)
