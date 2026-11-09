"""T3.1d CPU tests: ``pruefstand-lock`` takes the lock in-process (signals, exit codes, ``-c``).

Deterministic: the tests wait for a flag file the command writes once its trap is installed.
"""

import fcntl
import signal
import subprocess
import time
from pathlib import Path

import pytest
from vm_testkit import VM_DIR, Stubs, bash

LOCK = VM_DIR / "pruefstand-lock"
FLAG_DEADLINE_S = 30.0

# The command: trap TERM/INT/HUP, write its pid as the ready flag, then `wait` (a trapped signal
# interrupts `wait` at once, so there is no polling loop and no sleep-as-assert).
TRAPPED = (
    "sleep 600 & p=$!; "
    "trap 'kill $p; echo \"$$\" > got; exit 7' TERM INT HUP; "
    "echo $$ > ready; wait $p"
)


def _lock_dir(tmp_path: Path) -> Path:
    lock_dir = tmp_path / "lock"
    lock_dir.mkdir()
    (lock_dir / "gpu.lock").touch()
    return lock_dir


def _env(stubs: Stubs, lock_dir: Path, timeout_s: str = "5") -> dict[str, str]:
    return {
        "PATH": str(stubs.bin),
        "HOME": str(lock_dir.parent),
        "PRUEFSTAND_LOCK_DIR": str(lock_dir),
        "GPU_LOCK_TIMEOUT_S": timeout_s,
    }


def _run(
    stubs: Stubs, lock_dir: Path, *cmd: str, timeout_s: str = "5"
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [bash(), str(LOCK), *cmd],
        env=_env(stubs, lock_dir, timeout_s),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def _wait_for(flag: Path) -> None:
    deadline = time.monotonic() + FLAG_DEADLINE_S
    while not flag.exists():
        assert time.monotonic() < deadline, f"{flag.name} never appeared"
        time.sleep(0.01)  # polling a flag file the command writes; not a timing assertion


def _lock_is_free(lock_dir: Path) -> bool:
    with (lock_dir / "gpu.lock").open("rb") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        return True


def _start_trapped(stubs: Stubs, tmp_path: Path) -> tuple[subprocess.Popen[str], Path]:
    lock_dir = _lock_dir(tmp_path)
    proc = subprocess.Popen(  # noqa: S603
        [bash(), str(LOCK), "bash", "-c", TRAPPED],
        env=_env(stubs, lock_dir),
        cwd=tmp_path,
        text=True,
    )
    _wait_for(tmp_path / "ready")
    return proc, lock_dir


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT, signal.SIGHUP])
def test_a_signal_sent_to_pruefstand_lock_reaches_the_command(
    stubs: Stubs, tmp_path: Path, sig: signal.Signals
) -> None:
    """Killing the pid of pruefstand-lock must not orphan the command (it would keep the lock)."""
    proc, lock_dir = _start_trapped(stubs, tmp_path)
    assert int((tmp_path / "ready").read_text()) == proc.pid  # no helper process in between
    assert not _lock_is_free(lock_dir)
    proc.send_signal(sig)
    assert proc.wait(timeout=60) == 7
    assert (tmp_path / "got").exists()
    assert _lock_is_free(lock_dir)


def test_the_command_pid_is_the_holder_in_proc_locks(stubs: Stubs, tmp_path: Path) -> None:
    """The pruefstand-cluster wrapper looks for the holder among its ancestors."""
    proc, lock_dir = _start_trapped(stubs, tmp_path)
    try:
        inode = (lock_dir / "gpu.lock").stat().st_ino
        rows = [
            ln.split()
            for ln in Path("/proc/locks").read_text().splitlines()
            if "FLOCK" in ln and f":{inode} " in ln + " "
        ]
        assert [int(r[4]) for r in rows] == [proc.pid]
    finally:
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=60)


def test_a_command_exiting_75_does_not_print_gpu_lock_busy(stubs: Stubs, tmp_path: Path) -> None:
    res = _run(stubs, _lock_dir(tmp_path), "sh", "-c", "exit 75")
    assert res.returncode == 75
    assert "busy" not in res.stderr


def test_a_missing_command_exits_127_without_waiting_for_the_lock(
    stubs: Stubs, tmp_path: Path
) -> None:
    lock_dir = _lock_dir(tmp_path)
    with (lock_dir / "gpu.lock").open("rb") as holder:
        fcntl.flock(holder, fcntl.LOCK_EX)
        res = _run(stubs, lock_dir, "no-such-command-xyz", timeout_s="1")
    assert res.returncode == 127
    assert "command not found" in res.stderr
    assert "busy" not in res.stderr


def test_a_file_that_cannot_be_executed_is_reported_before_the_lock(
    stubs: Stubs, tmp_path: Path
) -> None:
    plain = tmp_path / "plain.txt"
    plain.write_text("not a program\n", encoding="utf-8")
    plain.chmod(0o644)
    res = _run(stubs, _lock_dir(tmp_path), str(plain))
    assert res.returncode == 127


def test_dash_c_belongs_to_the_command_not_to_flock(stubs: Stubs, tmp_path: Path) -> None:
    res = _run(stubs, _lock_dir(tmp_path), "bash", "-c", 'echo "$0|$1|$2"', "a", "-c")
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip() == "a|-c|"


def test_a_zero_timeout_does_not_wait(stubs: Stubs, tmp_path: Path) -> None:
    lock_dir = _lock_dir(tmp_path)
    with (lock_dir / "gpu.lock").open("rb") as holder:
        fcntl.flock(holder, fcntl.LOCK_EX)
        res = _run(stubs, lock_dir, "true", timeout_s="0")
    assert res.returncode == 75
    assert "gpu.lock busy" in res.stderr


def test_signals_python_ignores_are_not_inherited_by_the_command(
    stubs: Stubs, tmp_path: Path
) -> None:
    """SIGPIPE (bit 12 of SigIgn) and SIGXFSZ (bit 24) must be default again in the command."""
    res = _run(stubs, _lock_dir(tmp_path), "grep", "SigIgn", "/proc/self/status")
    ignored = int(res.stdout.split()[1], 16)
    assert ignored & (1 << 12) == 0
    assert ignored & (1 << 24) == 0
