"""GPU lock once per job, MAINTENANCE, lock timeout (X2.1, Y1.2, D212, P4.2); temp lock dirs."""

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from gate_orchestrator import lock as lock_mod
from gate_orchestrator.lock import (
    LockTimeoutError,
    child_env,
    gpu_lock,
    lock_path,
    maintenance_path,
    run_locked,
)
from gate_orchestrator.status import BUSY, MAINTENANCE
from orch_testkit import SpyPoster

SHA = "c" * 40
HOLDER = """
import fcntl, os, sys
fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT, 0o660)
fcntl.flock(fd, fcntl.LOCK_EX)
print("held", flush=True)
sys.stdin.readline()
"""


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def test_default_paths_are_on_the_vm_disk_not_home() -> None:
    assert lock_path() == Path("/var/lib/pruefstand/gpu.lock")
    assert maintenance_path() == Path("/var/lib/pruefstand/MAINTENANCE")
    source = Path(lock_mod.__file__).read_text(encoding="utf-8")
    assert "HOME" not in source.replace("home directory", "")
    assert "expanduser" not in source


def test_child_env_marks_the_lock_as_held() -> None:
    assert child_env({"PATH": "/usr/bin"}) == {"PATH": "/usr/bin", "PRUEFSTAND_LOCK_HELD": "1"}


def test_maintenance_posts_pending_and_takes_no_lock(tmp_path: Path, poster: SpyPoster) -> None:
    maintenance_path(tmp_path).write_text("", encoding="utf-8")
    ran: list[dict[str, str]] = []
    assert (
        run_locked(SHA, ran.append, poster=poster, env={}, timeout_s=5, lock_dir=tmp_path) is None
    )
    assert ran == []
    assert not lock_path(tmp_path).exists()
    assert poster.calls == [("post_status", SHA, "pending", MAINTENANCE, "pruefstand/gate")]
    assert MAINTENANCE == "executor in maintenance; dispatch again later"


def test_body_runs_once_under_the_lock_with_lock_held_env(
    tmp_path: Path, poster: SpyPoster
) -> None:
    def body(env: dict[str, str]) -> str:
        with (
            pytest.raises(LockTimeoutError),
            gpu_lock(lock_path(tmp_path), 0, sleep=lambda _s: None),
        ):
            pass
        return env["PRUEFSTAND_LOCK_HELD"]

    assert (
        run_locked(SHA, body, poster=poster, env={"A": "1"}, timeout_s=5, lock_dir=tmp_path) == "1"
    )
    assert poster.calls == []


def test_holder_with_another_home_blocks_until_timeout_then_releases(
    tmp_path: Path, poster: SpyPoster
) -> None:
    env = {**os.environ, "HOME": str(tmp_path / "other-home")}
    holder = subprocess.Popen(  # noqa: S603 - fixed argv, test-only interpreter
        [sys.executable, "-c", HOLDER, str(lock_path(tmp_path))],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "held"
        clock = FakeClock()
        ran: list[dict[str, str]] = []
        result = run_locked(
            SHA,
            ran.append,
            poster=poster,
            env={},
            timeout_s=7200,
            lock_dir=tmp_path,
            clock=clock,
            sleep=clock.sleep,
        )
        assert result is None
        assert ran == []
        assert clock.now >= 7200
        assert poster.calls == [("post_status", SHA, "pending", BUSY, "pruefstand/gate")]
        assert BUSY == "executor busy (GPU lock held); dispatch again"
    finally:
        holder.communicate("\n", timeout=10)
    assert (
        run_locked(SHA, lambda _e: "ok", poster=poster, env={}, timeout_s=5, lock_dir=tmp_path)
        == "ok"
    )


def test_second_job_waits_until_the_first_releases(tmp_path: Path, poster: SpyPoster) -> None:
    held, release = threading.Event(), threading.Event()
    order: list[str] = []

    def first() -> None:
        with gpu_lock(lock_path(tmp_path), 5):
            held.set()
            release.wait(10)
            order.append("first done")

    thread = threading.Thread(target=first)
    thread.start()
    assert held.wait(10)
    waits: list[float] = []

    def sleep(seconds: float) -> None:
        waits.append(seconds)
        release.set()
        time.sleep(0.02)

    run_locked(
        SHA,
        lambda _e: order.append("second ran"),
        poster=poster,
        env={},
        timeout_s=60,
        lock_dir=tmp_path,
        sleep=sleep,
    )
    thread.join(10)
    assert waits
    assert order == ["first done", "second ran"]
    assert poster.calls == []
