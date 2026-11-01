"""`make stack-run`: one lock hold, teardown on exit and on signals (T0.3, D357)."""

import os
import re
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
MAKE = shutil.which("make") or "make"


def _make(*args: str) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k not in {"PORT_OFFSET", "COMPOSE_PROJECT_NAME"}}
    env["PORT_OFFSET"] = "0"
    return subprocess.run(  # noqa: S603
        [MAKE, "-C", str(REPO), *args],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=120,
    )


def test_stack_run_holds_one_lock_with_a_teardown_trap(tmp_path: Path) -> None:
    lock = f"STACK_LOCK={tmp_path}/stack.lock"
    line = next(
        ln for ln in _make("-n", "stack-run", "CMD=true", lock).stdout.splitlines() if "flock" in ln
    )
    assert "stack.lock" in line
    assert 'make --no-print-directory down" EXIT' in line
    assert line.index("up WAIT=1") < line.index("true")


@pytest.mark.skipif(shutil.which("flock") is None, reason="needs flock")
@pytest.mark.parametrize("code", [0, 3])
def test_stack_run_tears_down_and_keeps_the_exit_code(tmp_path: Path, code: int) -> None:
    result = _make(
        "stack-run",
        f"CMD=echo checks; exit {code}",
        f"STACK_LOCK={tmp_path}/stack.lock",
        "COMPOSE_BASE=echo compose",
    )
    # make itself exits 2 when a recipe fails and reports the recipe's status ("Error 3")
    assert (result.returncode == 0) if code == 0 else f"Error {code}" in result.stderr
    lines = result.stdout.splitlines()
    assert any("up -d --wait" in ln for ln in lines)
    assert "checks" in lines
    assert any("down --remove-orphans" in ln for ln in lines)
    assert max(i for i, ln in enumerate(lines) if "down" in ln) > lines.index("checks")


@pytest.mark.skipif(shutil.which("flock") is None, reason="needs flock")
def test_stack_run_tears_down_when_up_fails(tmp_path: Path) -> None:
    result = _make(
        "stack-run",
        "CMD=echo checks",
        f"STACK_LOCK={tmp_path}/stack.lock",
        "COMPOSE_BASE=false",
    )
    assert result.returncode != 0
    assert "checks" not in result.stdout.splitlines()


def test_stack_run_lock_wait_is_optional(tmp_path: Path) -> None:
    # `make -n` still runs recipe lines containing $(MAKE), i.e. this flock: not on the shared lock
    lock = f"STACK_LOCK={tmp_path}/stack.lock"
    plain = _make("-n", "stack-run", "CMD=true", lock).stdout
    waiting = _make("-n", "stack-run", "CMD=true", "STACK_LOCK_WAIT=30", lock).stdout
    assert " -w 30 " in waiting
    assert "flock -w" not in plain


def _collect(proc: subprocess.Popen[str]) -> tuple[list[str], threading.Event, threading.Thread]:
    """Reads proc.stdout on a thread so that the test never blocks on the pipe."""
    lines: list[str] = []
    started = threading.Event()

    def pump() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            lines.append(line.rstrip())
            if line.strip() == "started":
                started.set()

    thread = threading.Thread(target=pump, daemon=True)
    thread.start()
    return lines, started, thread


def _group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    return True


@pytest.mark.skipif(shutil.which("flock") is None, reason="needs flock")
@pytest.mark.parametrize("mode", ["make", "group", "group-repeated"])
def test_stack_run_signalled_tears_down_and_leaves_no_process(tmp_path: Path, *, mode: str) -> None:
    """A TERM (to make alone, to its group, or repeated) stops CMD and still runs `down`.

    Synchronises on the `started` line CMD prints (CMD is then running), never on a sleep, and
    every wait has a generous deadline. Signal-to-exit time is bounded far below CMD's own 120 s, so
    a CMD that survives the signal (the old `set -m` failure under dash) fails the test.
    """
    proc = subprocess.Popen(  # noqa: S603
        [
            MAKE,
            "-C",
            str(REPO),
            "stack-run",
            f"STACK_LOCK={tmp_path}/stack.lock",
            "COMPOSE_BASE=echo compose",
            "CMD=echo started; sleep 120",
        ],
        stdout=subprocess.PIPE,
        text=True,
        start_new_session=True,
        env={**os.environ, "PORT_OFFSET": "0"},
    )
    lines, started, reader = _collect(proc)
    try:
        assert started.wait(timeout=120), f"CMD never started: {lines}"
        t0 = time.monotonic()
        if mode == "make":
            os.kill(proc.pid, signal.SIGTERM)  # make alone, not its children
        else:
            for _ in range(3 if mode == "group-repeated" else 1):
                os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=120)
        reader.join(timeout=120)
        assert not reader.is_alive(), "stdout still open: a process of the stack-run group survived"
        assert time.monotonic() - t0 < 60, "stack-run returned only after CMD ran to its end"
        deadline = time.monotonic() + 30
        while _group_alive(proc.pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not _group_alive(proc.pid), "processes of the stack-run group survived the signal"
    finally:
        if _group_alive(proc.pid):
            os.killpg(proc.pid, signal.SIGKILL)
    assert any("down --remove-orphans" in ln for ln in lines[lines.index("started") :]), lines


def test_stack_run_teardown_trap_ignores_further_signals(tmp_path: Path) -> None:
    lock = f"STACK_LOCK={tmp_path}/stack.lock"
    line = next(
        ln for ln in _make("-n", "stack-run", "CMD=true", lock).stdout.splitlines() if "flock" in ln
    )
    assert line.startswith("flock")
    assert " bash -c " in line  # dash cannot `set -m` without a tty
    assert re.search(r'trap "trap \\"\\" TERM INT; \S*make --no-print-directory down" EXIT', line)
    assert line.index("stop=1") < line.index("& pid=$!")  # handler installed before CMD is forked
