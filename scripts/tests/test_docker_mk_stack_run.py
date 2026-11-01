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
FLOCK = shutil.which("flock") or "flock"


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


CMD_PLAIN = (
    "echo started $$BASHPID; sleep 120"  # make turns $$ into $: the pid of CMD's group leader
)
CMD_DEAF = (
    'trap "" TERM; ' + CMD_PLAIN
)  # ignores TERM (and so does its sleep): needs the KILL escalation
SIGNALS = {
    "term": signal.SIGTERM,
    "int": signal.SIGINT,
    "hup": signal.SIGHUP,
    "quit": signal.SIGQUIT,
}
# GNU make forwards only TERM to its children; INT, HUP and QUIT reach them with the group (tty), so
# those are group cases only.
CASES = [
    ("term", "make", CMD_PLAIN, 1),
    ("term", "group", CMD_PLAIN, 1),
    ("term", "group", CMD_PLAIN, 3),  # repeated delivery must not abort the teardown
    ("int", "group", CMD_PLAIN, 1),
    ("hup", "group", CMD_PLAIN, 1),  # a closed SSH / VS Code terminal
    ("quit", "group", CMD_PLAIN, 1),
    ("term", "make", CMD_DEAF, 1),
]


def _collect(
    proc: subprocess.Popen[str],
) -> tuple[list[str], threading.Event, list[int], threading.Thread]:
    """Reads proc.stdout on a thread; `started <pgid>` marks CMD as running."""
    lines: list[str] = []
    cmd_pgid: list[int] = []
    started = threading.Event()

    def pump() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            lines.append(line.rstrip())
            if line.startswith("started "):
                cmd_pgid.append(int(line.split()[1]))
                started.set()

    thread = threading.Thread(target=pump, daemon=True)
    thread.start()
    return lines, started, cmd_pgid, thread


def _group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    return True


@pytest.mark.skipif(shutil.which("flock") is None, reason="needs flock")
@pytest.mark.parametrize(
    ("sig", "target", "cmd", "times"),
    CASES,
    ids=[
        f"{c[0]}-{c[1]}{'-x' + str(c[3]) if c[3] > 1 else ''}{'-deaf' if c[2] is CMD_DEAF else ''}"
        for c in CASES
    ],
)
def test_stack_run_signalled_tears_down_and_leaves_no_process(
    tmp_path: Path, sig: str, target: str, cmd: str, times: int
) -> None:
    """TERM/INT/HUP/QUIT (to make, to its group, repeated) stop CMD, run `down`, free the lock.

    Synchronises on the `started <pgid>` line CMD prints, never on a sleep; every wait has a
    generous deadline. CMD's own process group is checked directly, the lock must be free after,
    and signal-to-exit time is bounded far below CMD's 120 s, so a surviving CMD fails the test.
    """
    lock = tmp_path / "stack.lock"
    proc = subprocess.Popen(  # noqa: S603
        [
            MAKE,
            "-C",
            str(REPO),
            "stack-run",
            f"STACK_LOCK={lock}",
            "COMPOSE_BASE=echo compose",
            f"CMD={cmd}",
        ],
        stdout=subprocess.PIPE,
        text=True,
        start_new_session=True,
        env={**os.environ, "PORT_OFFSET": "0"},
    )
    lines, started, cmd_pgid, reader = _collect(proc)
    try:
        assert started.wait(timeout=120), f"CMD never started: {lines}"
        t0 = time.monotonic()
        for _ in range(times):
            (os.kill if target == "make" else os.killpg)(proc.pid, SIGNALS[sig])
        proc.wait(timeout=120)
        reader.join(timeout=120)
        assert not reader.is_alive(), (
            "stdout still open: a process of the stack survived the signal"
        )
        assert time.monotonic() - t0 < 60, "stack-run returned only after CMD ran to its end"
        deadline = time.monotonic() + 30
        while _group_alive(cmd_pgid[0]) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not _group_alive(cmd_pgid[0]), "CMD's process group survived the signal"
        free = subprocess.run([FLOCK, "-n", str(lock), "true"], check=False)  # noqa: S603
        assert free.returncode == 0, "stack.lock is still held"
    finally:
        for pgid in (cmd_pgid[0] if cmd_pgid else proc.pid, proc.pid):
            if _group_alive(pgid):
                os.killpg(pgid, signal.SIGKILL)
    assert any("down --remove-orphans" in ln for ln in lines if not ln.startswith("started")), lines


def test_stack_run_teardown_trap_ignores_further_signals(tmp_path: Path) -> None:
    lock = f"STACK_LOCK={tmp_path}/stack.lock"
    line = next(
        ln for ln in _make("-n", "stack-run", "CMD=true", lock).stdout.splitlines() if "flock" in ln
    )
    assert line.startswith("flock")
    assert " bash -c " in line  # dash cannot `set -m` without a tty
    assert re.search(
        r'trap "trap \\"\\" TERM INT HUP QUIT; \S*make --no-print-directory down" EXIT', line
    )
    assert "( trap - TERM INT HUP QUIT; true ) &" in line  # CMD starts with default handlers
    assert line.index("stop=1") < line.index("& pid=$!")  # handler installed before CMD is forked
