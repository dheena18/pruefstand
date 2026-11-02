"""T3.1a CPU tests: the lock rule of the VM scripts, static hardening, ``mk/gpu.mk`` (D211/D212)."""

import fcntl
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest
from gpu_testkit import GPU_DIR, REPO, run_script
from gpu_world import GpuWorld
from vm_testkit import Stubs, bash

LOCKED = ("switch-mode.sh", "health.sh", "fetch-model.sh", "unload-all.sh")
ARGS = {
    "switch-mode.sh": ("day",),
    "health.sh": (),
    "fetch-model.sh": ("ollama/bge-m3",),
    "unload-all.sh": (),
}
DRY = {"health.sh": ()}


@pytest.mark.parametrize("script", LOCKED)
def test_without_the_lock_flag_the_script_exits_2_at_once(gpu: GpuWorld, script: str) -> None:
    start = time.monotonic()
    res = run_script(
        GPU_DIR / script, *ARGS[script], stubs=gpu.stubs, env={"PRUEFSTAND_LOCK_HELD": ""}
    )
    assert res.rc == 2
    assert "run under the GPU lock: PRUEFSTAND_LOCK_HELD=1 not set" in res.err
    assert time.monotonic() - start < 2
    assert not gpu.stubs.calls("curl")
    assert not gpu.stubs.calls("ssh")


@pytest.mark.parametrize("script", LOCKED)
def test_with_the_flag_and_a_held_lock_the_script_does_not_wait(gpu: GpuWorld, script: str) -> None:
    with (gpu.lock_dir / "gpu.lock").open("rb") as holder:
        fcntl.flock(holder, fcntl.LOCK_EX)
        start = time.monotonic()
        res = gpu.script(script, *ARGS[script], *DRY.get(script, ("--dry-run",)))
        assert time.monotonic() - start < 2
    assert res.rc != 2, res.err


def test_the_vm_scripts_never_call_flock() -> None:
    for path in [*(GPU_DIR / s for s in LOCKED), *GPU_DIR.glob("lib/*.sh")]:
        text = path.read_text(encoding="utf-8")
        assert text.count("flock") == 0, path.name


def test_the_lock_wrapper_uses_one_file_for_two_users_and_the_second_waits(
    stubs: Stubs, tmp_path: Path
) -> None:
    lock_dir = tmp_path / "lock"
    lock_dir.mkdir()
    (lock_dir / "gpu.lock").touch()
    wrapper = REPO / "infra" / "vm" / "pruefstand-lock"
    env = {"PATH": str(stubs.bin), "PRUEFSTAND_LOCK_DIR": str(lock_dir), "GPU_LOCK_TIMEOUT_S": "1"}
    holder = subprocess.Popen(  # noqa: S603
        [bash(), str(wrapper), "sh", "-c", "echo ready; sleep 20"],
        env={**env, "HOME": str(tmp_path / "owner")}, stdout=subprocess.PIPE, text=True,
    )  # fmt: skip
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "ready"
        second = subprocess.run(  # noqa: S603
            [bash(), str(wrapper), "true"], env={**env, "HOME": str(tmp_path / "pruefstand")},
            capture_output=True, text=True, check=False, timeout=30,
        )  # fmt: skip
        assert second.returncode == 75
    finally:
        holder.kill()
        holder.wait()


def test_switch_mode_datagen_is_refused(gpu: GpuWorld) -> None:
    res = gpu.script("switch-mode.sh", "datagen")
    assert res.rc == 64
    assert "no datagen mode (ADR-0019)" in res.err
    assert not gpu.stubs.calls("curl")


@pytest.mark.parametrize("args", [(), ("noon",), ("day", "night")])
def test_switch_mode_needs_exactly_one_known_mode(gpu: GpuWorld, args: tuple[str, ...]) -> None:
    assert gpu.script("switch-mode.sh", *args).rc == 64


def test_no_vm_script_creates_or_removes_maintenance(gpu: GpuWorld) -> None:
    for path in [*(GPU_DIR / s for s in LOCKED), *GPU_DIR.glob("lib/*.sh")]:
        for line in path.read_text(encoding="utf-8").splitlines():
            code = line.split("#", 1)[0]
            if "MAINTENANCE" in code:
                assert not re.search(r"\b(touch|rm|mv|cp|tee)\b|>", code), (path.name, line)
    gpu.script("switch-mode.sh", "day", "--dry-run")
    assert not (gpu.lock_dir / "MAINTENANCE").exists()
    (gpu.lock_dir / "MAINTENANCE").touch()
    gpu.script("switch-mode.sh", "night", "--dry-run")
    gpu.script("health.sh")
    assert (gpu.lock_dir / "MAINTENANCE").exists()


def test_no_script_uses_the_v1_api_tmux_or_eval() -> None:
    for path in [*GPU_DIR.glob("*.sh"), *GPU_DIR.glob("lib/*.sh"), GPU_DIR / "pruefstand-cluster"]:
        code = "\n".join(
            ln
            for ln in path.read_text(encoding="utf-8").splitlines()
            if not ln.lstrip().startswith("#")
        )
        assert "/v1/" not in code, path.name
        assert not re.search(r"\b(tmux|eval)\b", code), path.name
        assert not re.search(r"\bset\s+\+e\b", code), path.name
        if path.parent.name != "lib":
            assert "set -euo pipefail" in path.read_text(encoding="utf-8"), path.name


def test_make_gpu_targets_take_the_lock_and_run_health_under_it() -> None:
    make = shutil.which("make") or "make"

    def dry(*targets: str) -> str:
        proc = subprocess.run(  # noqa: S603
            [make, "-n", "-C", str(REPO), *targets], capture_output=True, text=True, check=True
        )
        return proc.stdout

    up = dry("gpu-up")
    assert "pruefstand-lock" in up
    assert up.index("switch-mode.sh day") < up.index("health.sh")
    assert "switch-mode.sh night" in dry("gpu-night-up")
    assert "health.sh --repair" in dry("gpu-repair")
    assert "deploy-cluster-bin.sh" in dry("gpu-deploy-bin")
    assert "pruefstand-lock" not in dry("gpu-deploy-bin")  # deploy needs no lock
    for target in ("gpu-deploy-bin", "gpu-install-wrapper"):
        text = dry(target)
        assert "git archive origin/main infra/gpu infra/cluster" in text  # never the working tree
        assert "cp -r" not in text
    assert "install-cluster-wrapper.sh" in dry("gpu-install-wrapper")
    assert "fetch-model.sh ollama/bge-m3" in dry("gpu-pull", "ID=ollama/bge-m3")
    assert "fetch-model.sh --rm ollama/gemma3:12b" in dry("gpu-rm", "ID=ollama/gemma3:12b")
    down = dry("gpu-down")
    assert "pruefstand-lock" in down
    assert "unload-all.sh" in down
    assert re.search(r"pruefstand-lock .*make.* test-gpu", dry("test-gpu-locked"))


def test_make_gpu_pull_and_rm_require_an_id() -> None:
    make = shutil.which("make") or "make"
    for target in ("gpu-pull", "gpu-rm"):
        proc = subprocess.run(  # noqa: S603
            [make, "-n", "-C", str(REPO), target], capture_output=True, text=True, check=False
        )
        assert proc.returncode != 0
        assert "ID" in proc.stderr
