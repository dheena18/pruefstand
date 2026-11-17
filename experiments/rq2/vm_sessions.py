"""T5.4e full run: one launcher session of the VM judge, resumable (plan D1242, D1283, D1284).

One call = one session: preflight, ``vm_llm.sh start 14b`` (it takes ``pruefstand-lock`` and every
check slot for the server's life), then the VM judge scores the planned items one at a time
through the RQ2 judge disk cache, so the next session skips every cached item and continues where
this one stopped. Before every call the session stops cleanly (current call finished, server
stopped by ``finally``) when

* another process is **blocked on a lock our server holds** (a gate job on ``gpu.lock`` or a
  ``make check-vm`` on a check slot): read from ``/proc/locks`` alone (D1284; agents never touch
  ``/var/lib/pruefstand/**``, not even a ``stat``); if our holder's lock lines are not found the
  session stops (fail safe);
* the session deadline is reached: 240 min x 0.8 or 21:55 Europe/Berlin (night window, D223);
* the stop file ``~/pruefstand/rq2-vm.stop`` exists.

When every call is cached, ``run_judges.py`` writes the final parquets (all cache hits) and the
session prints ``done``.

    uv run python experiments/rq2/vm_session_run.py [--pairs] [--sets ...] [--limit N] [--dry-run]
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from rq2.vm_arm import SESSION_S, SESSION_USE

BERLIN = ZoneInfo("Europe/Berlin")
NIGHT_START, NIGHT_END = time(22, 0), time(6, 0)
STOP_BEFORE_NIGHT = timedelta(minutes=5)
START_BEFORE_NIGHT = timedelta(minutes=30)
# A session is capped BELOW the gate job's 2 h lock wait (gate_job.LOCK_TIMEOUT_S, a test keeps it
# so): the orchestrator and vm_check poll with LOCK_NB and never show up as blocked waiters in
# /proc/locks; the cap, not the /proc/locks check, lets a waiting gate job in (D1284).
SESSION_MIN = SESSION_S // 60
STOP_FILE = Path.home() / "pruefstand" / "rq2-vm.stop"
LOCK_LINE = re.compile(
    r"^\d+:\s+(?P<blocked>->\s+)?\S+\s+\S+\s+\S+\s+(?P<pid>\d+)\s+(?P<id>[0-9a-f]+:[0-9a-f]+:\d+)\s"
)


@dataclass(frozen=True)
class LockLine:
    """One line of ``/proc/locks``: owner pid, ``major:minor:inode`` and whether it waits."""

    pid: int
    lock_id: str
    blocked: bool


def parse_locks(text: str) -> list[LockLine]:
    r"""Parse ``/proc/locks`` (held and blocked ``->`` lines; anything else is skipped).

    Examples:
        >>> held, waiting = parse_locks("1: FLOCK  ADVISORY  WRITE 11250 00:1d:4754 0 EOF\n"
        ...                             "1: -> FLOCK  ADVISORY  WRITE 4242 00:1d:4754 0 EOF\n")
        >>> held.blocked, waiting.blocked, waiting.lock_id
        (False, True, '00:1d:4754')
    """
    out = []
    for line in text.splitlines():
        match = LOCK_LINE.match(line)
        if match:
            out.append(LockLine(int(match["pid"]), match["id"], match["blocked"] is not None))
    return out


def lock_wanted(text: str, holders: Iterable[int]) -> bool | None:
    """Whether another process waits for a lock that one of ``holders`` holds.

    Returns:
        True / False, or None when no ``holders`` lock is listed (the caller stops: fail safe).
    """
    lines = parse_locks(text)
    pids = set(holders)
    held = {line.lock_id for line in lines if not line.blocked and line.pid in pids}
    if not held:
        return None
    return any(line.blocked and line.lock_id in held for line in lines)


def in_night(now: datetime) -> bool:
    """Whether ``now`` (aware) lies in the night window 22:00-06:00 Europe/Berlin."""
    clock = now.astimezone(BERLIN).time()
    return clock >= NIGHT_START or clock < NIGHT_END


def deadline(start: datetime, minutes: int = SESSION_MIN, use: float = SESSION_USE) -> datetime:
    """The session's last call start: ``minutes x use`` after ``start``, at the latest 21:55 Berlin.

    Examples:
        >>> d = deadline(datetime(2026, 11, 17, 21, 0, tzinfo=BERLIN))
        >>> d.astimezone(BERLIN).strftime("%H:%M")
        '21:55'
    """
    local = start.astimezone(BERLIN)
    night = datetime.combine(local.date(), NIGHT_START, BERLIN) - STOP_BEFORE_NIGHT
    return min(local + timedelta(minutes=minutes * use), night)


def start_refusal(now: datetime) -> str | None:
    """Why a session may not start now (night window, too close to it, stop file), or None."""
    local = now.astimezone(BERLIN)
    if in_night(local):
        return "night window (22:00-06:00 Europe/Berlin)"
    if datetime.combine(local.date(), NIGHT_START, BERLIN) - local < START_BEFORE_NIGHT:
        return "less than 30 min before the night window"
    if STOP_FILE.exists():
        return f"stop file {STOP_FILE}"
    return None


def stop_reason(now: datetime, until: datetime, locks: str, holders: Sequence[int]) -> str | None:
    """Why the session stops before the next call, or None to go on."""
    if now >= until:
        return "deadline"
    if STOP_FILE.exists():
        return "stop file"
    wanted = lock_wanted(locks, holders)
    if wanted is None:
        return "holder lock not found in /proc/locks (fail safe)"
    return "lock wanted" if wanted else None


def ancestors(pid: int, proc: Path = Path("/proc")) -> list[int]:
    """``pid`` and its parents up to (not including) pid 1, from ``/proc/<pid>/stat``."""
    chain = []
    while pid > 1:
        chain.append(pid)
        try:
            stat = (proc / str(pid) / "stat").read_text(encoding="utf-8")
        except OSError:
            break
        pid = int(stat.rsplit(")", 1)[1].split()[1])
    return chain


def server_pid(state: Path, proc: Path = Path("/proc")) -> int | None:
    """The live ``llama-server`` pid from ``vm_llm.sh``'s PID file, or None."""
    try:
        pid = int((state / "pid").read_text(encoding="utf-8").split()[0])
        cmd = (proc / str(pid) / "cmdline").read_bytes()
    except (OSError, ValueError, IndexError):
        return None
    return pid if b"llama-server" in cmd else None


def current_stop(
    until: datetime, holders: Sequence[int], locks: Path = Path("/proc/locks")
) -> str | None:
    """``stop_reason`` now, with ``/proc/locks`` read fresh (the only lock source, D1284)."""
    return stop_reason(datetime.now(UTC), until, locks.read_text(encoding="utf-8"), holders)
