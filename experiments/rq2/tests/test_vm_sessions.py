"""T5.4e session driver guards (D1284): /proc/locks lock-wanted, night window, deadline, stops."""

from datetime import datetime, timedelta
from pathlib import Path

import pytest
from rq2 import vm_sessions
from rq2.vm_sessions import (
    BERLIN,
    LockLine,
    ancestors,
    deadline,
    in_night,
    lock_wanted,
    parse_locks,
    server_pid,
    start_refusal,
    stop_reason,
)

# real /proc/locks line formats (a VM sample): held flocks, a blocked waiter, a POSIX lock
LOCKS = """1: FLOCK  ADVISORY  WRITE 11250 00:1d:4754 0 EOF
2: FLOCK  ADVISORY  WRITE 11937 08:02:16515336 0 EOF
2: -> FLOCK  ADVISORY  WRITE 20001 08:02:16515336 0 EOF
3: FLOCK  ADVISORY  WRITE 11937 08:02:16515331 0 EOF
4: POSIX  ADVISORY  WRITE 10886 08:02:16391226 0 EOF
"""


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, 17, hour, minute, tzinfo=BERLIN)


def test_parse_locks_reads_held_and_blocked_lines() -> None:
    lines = parse_locks(LOCKS + "garbage line\n")
    assert lines[1] == LockLine(11937, "08:02:16515336", blocked=False)
    assert lines[2] == LockLine(20001, "08:02:16515336", blocked=True)
    assert len(lines) == 5


def test_a_waiter_on_a_lock_we_hold_means_lock_wanted() -> None:
    assert lock_wanted(LOCKS, [11937]) is True  # someone waits on 08:02:16515336
    assert lock_wanted(LOCKS, [11250]) is False  # nobody waits on 00:1d:4754
    assert lock_wanted(LOCKS, [99999]) is None  # our holder holds nothing: fail safe


def test_a_waiter_on_someone_else_s_lock_is_not_ours() -> None:
    other = (
        "1: FLOCK  ADVISORY  WRITE 500 00:1d:1 0 EOF\n"
        "1: -> FLOCK  ADVISORY  WRITE 501 00:1d:1 0 EOF\n"
    )
    assert lock_wanted(LOCKS + other, [11250]) is False


def test_night_window_and_start_margin(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(vm_sessions, "STOP_FILE", tmp_path / "rq2-vm.stop")
    assert in_night(at(22))
    assert in_night(at(5, 59))
    assert not in_night(at(6))
    assert start_refusal(at(10)) is None
    assert "night window" in str(start_refusal(at(23)))
    assert "30 min" in str(start_refusal(at(21, 40)))
    (tmp_path / "rq2-vm.stop").write_text("", encoding="utf-8")
    assert "stop file" in str(start_refusal(at(10)))


def test_deadline_is_the_session_budget_or_21_55() -> None:
    assert deadline(at(10)) == at(11, 30)  # 100 min x 0.9
    assert deadline(at(21)) == at(21, 55)


def test_stop_reasons(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(vm_sessions, "STOP_FILE", tmp_path / "rq2-vm.stop")
    until = at(13)
    assert stop_reason(at(12), until, LOCKS, [11250]) is None
    assert stop_reason(at(13), until, LOCKS, [11250]) == "deadline"
    assert stop_reason(at(12), until, LOCKS, [11937]) == "lock wanted"
    assert "fail safe" in str(stop_reason(at(12), until, LOCKS, []))
    (tmp_path / "rq2-vm.stop").write_text("", encoding="utf-8")
    assert stop_reason(at(12), until, LOCKS, [11250]) == "stop file"


def test_ancestors_follow_ppid_up_to_init(tmp_path: Path) -> None:
    for pid, ppid in ((300, 200), (200, 100), (100, 1)):
        (tmp_path / str(pid)).mkdir()
        (tmp_path / str(pid) / "stat").write_text(f"{pid} (a b) S {ppid} 0 0", encoding="utf-8")
    assert ancestors(300, tmp_path) == [300, 200, 100]
    assert ancestors(42, tmp_path) == [42]  # gone: the pid alone


def test_the_session_cap_is_below_the_gate_s_lock_wait() -> None:
    """Polling waiters are invisible in /proc/locks: the cap is the real protection (D1284)."""
    from gate_orchestrator.gate_job import LOCK_TIMEOUT_S  # noqa: PLC0415  (other import root)

    assert vm_sessions.SESSION_MIN * 60 < LOCK_TIMEOUT_S
    start = at(10)
    assert deadline(start) - start <= timedelta(minutes=vm_sessions.SESSION_MIN)


def test_a_start_in_the_night_is_refused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(vm_sessions, "STOP_FILE", tmp_path / "rq2-vm.stop")
    assert "night window" in str(start_refusal(at(2)))
    assert "night window" in str(start_refusal(at(5, 59)))


def test_server_pid_needs_a_llama_server_cmdline(tmp_path: Path) -> None:
    state, proc = tmp_path / "state", tmp_path / "proc"
    state.mkdir()
    (proc / "77").mkdir(parents=True)
    (state / "pid").write_text("77 123 tok\n", encoding="utf-8")
    (proc / "77" / "cmdline").write_bytes(b"/opt/llama-server\x00--port\x0018091\x00")
    assert server_pid(state, proc) == 77
    (proc / "77" / "cmdline").write_bytes(b"/usr/bin/python3\x00other\x00")
    assert server_pid(state, proc) is None  # a recycled pid is never taken for our server
