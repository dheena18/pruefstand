"""D1083: the probe's process group on timeout: TERM first (traps run), then KILL, bounded waits.

These tests start real short-lived processes (``sh``, ``sleep``); every process they start is
waited for or killed by its exact pid.
"""

import contextlib
import os
import signal
import subprocess
import time
from pathlib import Path

import pytest
from gate_orchestrator.post_run import subprocess_runner

ENV = {"PATH": os.environ.get("PATH", "")}


def _gone(pid: int, within_s: float = 5) -> bool:
    deadline = time.monotonic() + within_s
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.05)
    return False


def test_timeout_kills_the_grandchild_and_returns_at_once(tmp_path: Path) -> None:
    pidfile = tmp_path / "grandchild.pid"
    script = f"sleep 30 >/dev/null 2>&1 & echo $! > {pidfile}; wait"
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        subprocess_runner(("sh", "-c", script), ENV, 0.5)
    assert time.monotonic() - started < 15  # well under the grandchild's 30 s
    assert _gone(int(pidfile.read_text(encoding="utf-8")))


def test_sigterm_first_lets_the_exit_trap_clean_up(tmp_path: Path) -> None:
    marker = tmp_path / "tmpdir.txt"
    script = (
        f'd=$(mktemp -d -p {tmp_path}); echo "$d" > {marker}; trap \'rm -rf "$d"\' EXIT; '
        "sleep 30 >/dev/null 2>&1"
    )
    with pytest.raises(subprocess.TimeoutExpired):
        subprocess_runner(("bash", "-c", script), ENV, 0.5)
    left = Path(marker.read_text(encoding="utf-8").strip())
    assert not left.exists()  # health.sh's trap 'rm -rf $tmp' EXIT ran (SIGKILL would skip it)


def test_a_daemon_holding_the_pipe_cannot_block_the_runner(tmp_path: Path) -> None:
    pidfile = tmp_path / "daemon.pid"
    script = f"setsid sh -c 'echo $$ > {pidfile}; exec sleep 30' & sleep 30 >/dev/null 2>&1"
    started = time.monotonic()
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            subprocess_runner(("sh", "-c", script), ENV, 0.5)
        assert time.monotonic() - started < 15  # TERM grace 2 s + bounded drain, not 30 s
    finally:
        if pidfile.exists():
            pid = int(pidfile.read_text(encoding="utf-8"))
            with contextlib.suppress(ProcessLookupError):
                os.kill(pid, signal.SIGKILL)  # the daemon this test started, by exact pid
