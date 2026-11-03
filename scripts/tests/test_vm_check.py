"""``scripts/vm_check.sh``: at most N concurrent `make check` runs on the shared VM (D660)."""

import fcntl
import os
import subprocess
import time
from pathlib import Path

import pytest

# Several tests spawn real subprocesses and take about 20 s: the repo convention for > 10 s is `slow`
# (excluded from `make test`, run by `make test-slow`), so they cannot disturb the timing-sensitive unit tests.
pytestmark = pytest.mark.slow

SCRIPT = Path(__file__).resolve().parents[1] / "vm_check.sh"


def _env(tmp_path: Path, slots: str) -> dict[str, str]:
    """A fake ``make`` that records its start and end and sleeps, so concurrency is observable."""
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    fake = bindir / "make"
    log = tmp_path / "events.log"
    body = (
        f'#!/bin/sh\necho "start $$" >> "{log}"\nsleep 1\n'
        f'echo "end $$" >> "{log}"\nexit "${{FAKE_RC:-0}}"\n'
    )
    fake.write_text(body, encoding="utf-8")
    fake.chmod(0o755)
    return {
        **os.environ,
        "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
        "PRUEFSTAND_CHECK_SLOTS": slots,
        "PRUEFSTAND_CHECK_DIR": str(tmp_path / "locks"),
    }


def _peak(log: Path) -> int:
    running = peak = 0
    for line in log.read_text(encoding="utf-8").splitlines():
        running += 1 if line.startswith("start") else -1
        peak = max(peak, running)
    return peak


def _run(env: dict[str, str]) -> subprocess.Popen[bytes]:
    return subprocess.Popen([str(SCRIPT)], env=env, stderr=subprocess.PIPE)  # noqa: S603  # fixed argv


def test_five_runs_with_two_slots_never_run_three_at_once(tmp_path: Path) -> None:
    env = _env(tmp_path, "2")
    procs = [_run(env) for _ in range(5)]
    assert [p.wait(timeout=120) for p in procs] == [0] * 5
    log = tmp_path / "events.log"
    assert log.read_text(encoding="utf-8").count("start") == 5
    assert _peak(log) <= 2


def test_one_slot_serialises_runs(tmp_path: Path) -> None:
    env = _env(tmp_path, "1")
    procs = [_run(env) for _ in range(2)]
    assert [p.wait(timeout=60) for p in procs] == [0, 0]
    assert _peak(tmp_path / "events.log") == 1


def test_the_exit_code_of_make_is_passed_on(tmp_path: Path) -> None:
    env = {**_env(tmp_path, "2"), "FAKE_RC": "3"}
    assert subprocess.run([str(SCRIPT)], env=env, check=False, timeout=60).returncode == 3  # noqa: S603


def test_with_every_slot_held_the_run_waits_and_starts_when_one_frees(tmp_path: Path) -> None:
    env = _env(tmp_path, "2")
    locks = tmp_path / "locks"
    locks.mkdir()
    held = []
    for i in (1, 2):
        fh = (locks / f"slot{i}.lock").open("w")
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        held.append(fh)
    proc = _run(env)
    time.sleep(1.5)
    assert proc.poll() is None  # still waiting
    assert not (tmp_path / "events.log").exists()
    fcntl.flock(held[0], fcntl.LOCK_UN)
    assert proc.wait(timeout=60) == 0
    assert proc.stderr is not None
    assert "busy, waiting" in proc.stderr.read().decode()
    assert (tmp_path / "events.log").read_text(encoding="utf-8").count("start") == 1


def test_a_signal_to_the_script_reaches_make_and_frees_the_slot(tmp_path: Path) -> None:
    env = _env(tmp_path, "1")
    first = _run(env)
    deadline = time.monotonic() + 10
    log = tmp_path / "events.log"
    while not log.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    first.terminate()  # the script exec'd make: this is make
    first.wait(timeout=10)
    second = _run(env)
    assert second.wait(timeout=60) == 0  # the slot was free again


def test_invalid_slot_counts_are_refused_with_exit_2(tmp_path: Path) -> None:
    for bad in ("0", "x", "-1", "1.5"):
        env = _env(tmp_path, bad)
        res = subprocess.run([str(SCRIPT)], env=env, capture_output=True, check=False, timeout=30)  # noqa: S603
        assert res.returncode == 2, bad
        assert b"whole number" in res.stderr


def test_an_unwritable_cache_dir_is_a_clear_error(tmp_path: Path) -> None:
    env = {**_env(tmp_path, "2"), "PRUEFSTAND_CHECK_DIR": "/proc/nope/locks"}
    res = subprocess.run([str(SCRIPT)], env=env, capture_output=True, check=False, timeout=30)  # noqa: S603
    assert res.returncode == 2
    assert b"cannot create" in res.stderr
