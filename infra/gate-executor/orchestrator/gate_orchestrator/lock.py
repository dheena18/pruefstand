"""The host GPU lock, taken once per job (X2.1, Y1.1/Y1.2, D101, D200, D211, D212).

The orchestrator takes ``flock`` on ``/var/lib/pruefstand/gpu.lock`` (the VM's local disk; never a
home directory or the data root) exactly once per job and exports ``PRUEFSTAND_LOCK_HELD=1`` to its
children, so ``switch-mode.sh``/``health.sh``/``fetch-model.sh`` never lock again. Owner and agent
GPU commands take the same file through ``pruefstand-lock`` (``flock(1)``, which shares
``flock(2)`` semantics with this module). Order: ``MAINTENANCE`` check (no lock taken) → lock wait →
the job body (preflight first). Tests pass a temporary ``lock_dir``.
"""

import fcntl
import os
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path

from gate_orchestrator.status import BUSY, MAINTENANCE, StatusPoster
from pruefstand.core.errors import PruefstandError

LOCK_DIR = Path("/var/lib/pruefstand")
LOCK_HELD_ENV = "PRUEFSTAND_LOCK_HELD"


class LockTimeoutError(PruefstandError):
    """The GPU lock was not obtained within the timeout."""


def lock_path(lock_dir: Path = LOCK_DIR) -> Path:
    """``<lock_dir>/gpu.lock`` (default ``/var/lib/pruefstand/gpu.lock``)."""
    return lock_dir / "gpu.lock"


def maintenance_path(lock_dir: Path = LOCK_DIR) -> Path:
    """``<lock_dir>/MAINTENANCE`` (default ``/var/lib/pruefstand/MAINTENANCE``)."""
    return lock_dir / "MAINTENANCE"


@contextmanager
def gpu_lock(
    path: Path,
    timeout_s: float,
    *,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    poll_s: float = 1.0,
) -> Iterator[None]:
    """Hold an exclusive ``flock`` on ``path`` (waits up to ``timeout_s``; ``flock -w`` semantics).

    Raises:
        LockTimeoutError: the lock is still held by someone else after ``timeout_s``.
    """
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o660)
    try:
        start = clock()
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if clock() - start >= timeout_s:
                    msg = f"GPU lock {path} not obtained within {timeout_s:.0f} s"
                    raise LockTimeoutError(msg) from None
                sleep(poll_s)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def child_env(base: Mapping[str, str]) -> dict[str, str]:
    """``base`` plus ``PRUEFSTAND_LOCK_HELD=1`` for every child of a locked job."""
    return {**base, LOCK_HELD_ENV: "1"}


def run_locked[T](
    sha: str,
    body: Callable[[dict[str, str]], T],
    *,
    poster: StatusPoster,
    env: Mapping[str, str],
    timeout_s: float,
    lock_dir: Path = LOCK_DIR,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> T | None:
    """Run one job's ``body`` under the GPU lock, taken once.

    Args:
        sha: commit the ``pending`` statuses go to.
        body: the job (preflight first); receives the child env with ``PRUEFSTAND_LOCK_HELD=1``.
        poster: status poster (``post_status`` only here).
        env: the base environment for children.
        timeout_s: lock wait (≤ 2 h for PR and promote jobs).
        lock_dir: directory of ``gpu.lock`` and ``MAINTENANCE``.
        clock: monotonic clock (injected in tests).
        sleep: sleep function (injected in tests).

    Returns:
        ``body``'s result, or ``None`` when ``MAINTENANCE`` is present (no lock taken) or the lock
        wait timed out; both post ``pending`` and record nothing.
    """
    if maintenance_path(lock_dir).exists():
        poster.post_status(sha, "pending", MAINTENANCE)
        return None
    try:
        with gpu_lock(lock_path(lock_dir), timeout_s, clock=clock, sleep=sleep):
            return body(child_env(env))
    except LockTimeoutError:
        poster.post_status(sha, "pending", BUSY)
        return None
