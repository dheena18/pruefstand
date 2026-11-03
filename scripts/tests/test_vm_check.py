"""``scripts/vm_check.sh``: at most N concurrent `make check` runs on the shared VM (D660)."""

import os
import subprocess
import time
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "vm_check.sh"


def _env(tmp_path: Path, slots: int) -> dict[str, str]:
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
        "PRUEFSTAND_CHECK_SLOTS": str(slots),
        "PRUEFSTAND_CHECK_DIR": str(tmp_path / "locks"),
    }


def _max_concurrent(log: Path) -> int:
    running = peak = 0
    for line in log.read_text(encoding="utf-8").splitlines():
        running += 1 if line.startswith("start") else -1
        peak = max(peak, running)
    return peak


def test_three_runs_with_two_slots_never_run_three_at_once(tmp_path: Path) -> None:
    env = _env(tmp_path, 2)
    procs = [subprocess.Popen([str(SCRIPT)], env=env, stderr=subprocess.PIPE) for _ in range(3)]  # noqa: S603  # fixed argv, no shell
    codes = [p.wait(timeout=60) for p in procs]
    assert codes == [0, 0, 0]
    log = tmp_path / "events.log"
    assert log.read_text(encoding="utf-8").count("start") == 3
    assert _max_concurrent(log) == 2


def test_one_slot_serialises_runs(tmp_path: Path) -> None:
    env = _env(tmp_path, 1)
    procs = [subprocess.Popen([str(SCRIPT)], env=env, stderr=subprocess.PIPE) for _ in range(2)]  # noqa: S603  # fixed argv, no shell
    assert [p.wait(timeout=60) for p in procs] == [0, 0]
    assert _max_concurrent(tmp_path / "events.log") == 1


def test_the_exit_code_of_make_is_passed_on(tmp_path: Path) -> None:
    env = {**_env(tmp_path, 2), "FAKE_RC": "3"}
    assert subprocess.run([str(SCRIPT)], env=env, check=False, timeout=60).returncode == 3  # noqa: S603  # fixed argv, no shell


def test_a_waiting_run_says_so_and_starts_when_a_slot_frees(tmp_path: Path) -> None:
    env = _env(tmp_path, 1)
    first = subprocess.Popen([str(SCRIPT)], env=env)  # noqa: S603  # fixed argv, no shell
    time.sleep(0.3)
    second = subprocess.run(  # noqa: S603  # fixed argv, no shell
        [str(SCRIPT)], env=env, capture_output=True, text=True, check=False, timeout=60
    )
    assert first.wait(timeout=60) == 0
    assert second.returncode == 0
    assert "slots busy, waiting" in second.stderr
