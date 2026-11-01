"""T0.7 CPU tests: the ``pruefstand-lock`` wrapper (A11-01, D211/D212)."""

import fcntl
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from vm_testkit import VM_DIR, Stubs, bash


def _lock_dir(tmp_path: Path) -> Path:
    lock_dir = tmp_path / "lock"
    lock_dir.mkdir()
    (lock_dir / "gpu.lock").touch()
    return lock_dir


def _run_lock(
    stubs: Stubs, lock_dir: Path, home: Path, *cmd: str, timeout_s: str = "5"
) -> subprocess.CompletedProcess[str]:
    env = {
        "PATH": str(stubs.bin),
        "HOME": str(home),
        "PRUEFSTAND_LOCK_DIR": str(lock_dir),
        "GPU_LOCK_TIMEOUT_S": timeout_s,
    }
    return subprocess.run(  # noqa: S603
        [shutil.which("bash") or "bash", str(VM_DIR / "pruefstand-lock"), *cmd],
        env=env, capture_output=True, text=True, timeout=60, check=False,
    )  # fmt: skip


def test_lock_runs_command_with_lock_held_flag_and_returns_its_rc(
    stubs: Stubs, tmp_path: Path
) -> None:
    lock_dir = _lock_dir(tmp_path)
    ok = _run_lock(stubs, lock_dir, tmp_path / "a", "sh", "-c", 'echo "held=$PRUEFSTAND_LOCK_HELD"')
    assert ok.returncode == 0
    assert "held=1" in ok.stdout
    assert _run_lock(stubs, lock_dir, tmp_path / "a", "sh", "-c", "exit 7").returncode == 7


def test_lock_busy_exits_75_across_homes(stubs: Stubs, tmp_path: Path) -> None:
    lock_dir = _lock_dir(tmp_path)
    holder = subprocess.Popen(  # noqa: S603
        [bash(), str(VM_DIR / "pruefstand-lock"), "sh", "-c", "echo ready; sleep 20"],
        env={"PATH": str(stubs.bin), "PRUEFSTAND_LOCK_DIR": str(lock_dir), "HOME": str(tmp_path)},
        stdout=subprocess.PIPE, text=True,
    )  # fmt: skip
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "ready"
        res = _run_lock(stubs, lock_dir, tmp_path / "other-home", "true", timeout_s="1")
        assert res.returncode == 75
        assert "gpu.lock busy" in res.stderr
    finally:
        holder.kill()
        holder.wait()


def test_lock_without_command_or_lock_file_fails_cleanly(stubs: Stubs, tmp_path: Path) -> None:
    assert _run_lock(stubs, _lock_dir(tmp_path), tmp_path).returncode == 64
    empty = tmp_path / "empty"
    empty.mkdir()
    res = _run_lock(stubs, empty, tmp_path, "true")
    assert res.returncode == 2
    assert "setup-users.sh" in res.stderr


def test_lock_nested_call_does_not_wait(stubs: Stubs, tmp_path: Path) -> None:
    lock_dir = _lock_dir(tmp_path)
    with (lock_dir / "gpu.lock").open("rb") as holder:
        fcntl.flock(holder, fcntl.LOCK_EX)
        env = {
            "PATH": str(stubs.bin),
            "PRUEFSTAND_LOCK_DIR": str(lock_dir),
            "PRUEFSTAND_LOCK_HELD": "1",
        }
        res = subprocess.run(  # noqa: S603
            [bash(), str(VM_DIR / "pruefstand-lock"), "true"],
            env=env, capture_output=True, text=True, timeout=30, check=False,
        )  # fmt: skip
    assert res.returncode == 0


def test_lock_rejects_a_non_numeric_timeout(stubs: Stubs, tmp_path: Path) -> None:
    res = _run_lock(stubs, _lock_dir(tmp_path), tmp_path, "true", timeout_s="soon")
    assert res.returncode == 64
    assert "GPU_LOCK_TIMEOUT_S" in res.stderr


def test_lock_names_the_group_when_it_cannot_open_the_file(stubs: Stubs, tmp_path: Path) -> None:
    if os.geteuid() == 0:
        pytest.skip("root can open any file")
    lock_dir = _lock_dir(tmp_path)
    (lock_dir / "gpu.lock").chmod(0)
    res = _run_lock(stubs, lock_dir, tmp_path, "true")
    assert res.returncode == 2
    assert "group pruefstand" in res.stderr
