"""T5.4e session runner: the planned calls match run_judges (resume = the judge cache)."""

import argparse
import signal
import subprocess

import pytest
from rq2 import vm_session_run as run_mod
from rq2.vm_session_run import _inputs, planned_tasks

SETS = ["faithfulness_constructed", "correctness", "refusal", "consistency"]


def test_the_plan_is_run_judges_selection_in_order() -> None:
    args = argparse.Namespace(sets=SETS, limit=2, pairs=False)
    tasks = planned_tasks(args)
    assert len(tasks) == 2 * len(SETS)
    assert tasks == planned_tasks(args)  # same order every session: the cache keys repeat


def test_pair_inputs_must_be_objects() -> None:
    assert _inputs({"answer": "Ja.", "n": 1}) == {"answer": "Ja.", "n": "1"}
    with pytest.raises(TypeError, match="object"):
        _inputs(["not", "an", "object"])


def test_the_server_is_stopped_even_when_the_session_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake_run(argv: list[str], **_kw: object) -> subprocess.CompletedProcess[str]:
        calls.append([str(a) for a in argv])
        return subprocess.CompletedProcess(argv, 0)

    def boom(_state: object) -> int:
        msg = "holder lookup failed"
        raise RuntimeError(msg)

    monkeypatch.setattr(run_mod, "start_refusal", lambda _now: None)
    monkeypatch.setattr(run_mod, "planned_tasks", lambda _a: [])
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(run_mod, "server_pid", boom)
    monkeypatch.setattr(run_mod, "_log", lambda _row: None)
    with pytest.raises(RuntimeError, match="holder lookup"):
        run_mod.run_session(argparse.Namespace(sets=None, limit=None, pairs=False))
    assert calls[0][-2:] == ["start", "14b"]
    assert calls[-1][-1] == "stop"


def test_sigterm_unwinds_into_the_server_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[object] = []

    def fake_session(_args: object) -> int:
        seen.append(signal.getsignal(signal.SIGTERM))
        return 0

    monkeypatch.setattr(run_mod, "run_session", fake_session)
    before = signal.getsignal(signal.SIGTERM)
    try:
        assert run_mod.main([]) == 0
        assert seen == [run_mod._terminate]
    finally:
        signal.signal(signal.SIGTERM, before)
    with pytest.raises(SystemExit) as exit_info:
        run_mod._terminate(signal.SIGTERM, None)
    assert exit_info.value.code == 128 + signal.SIGTERM
