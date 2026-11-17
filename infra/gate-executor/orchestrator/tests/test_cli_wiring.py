"""The CLI entry points wire the real index check (review #259): no silent ``aliases=None``."""

import argparse
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from gate_orchestrator import cmd_dispatch, cmd_nightly, cmd_promote
from gate_orchestrator.index_job import qdrant_aliases
from gate_orchestrator.models import Dispatch, Job

TOKEN = "ghs_" + "x" * 36


def test_promote_poll_uses_the_qdrant_index_check(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: list[Any] = []

    def capture(deps: Any, work: Path) -> list[str]:
        seen.append(deps)
        return []

    monkeypatch.setattr(cmd_promote, "run_poll", capture)
    cmd_promote.promote_poll(argparse.Namespace(report_dir=str(tmp_path)))
    assert seen[0].aliases is qdrant_aliases


def test_nightly_uses_the_qdrant_index_check(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: list[Any] = []

    def capture(deadline: datetime, report: Path, deps: Any) -> int:
        seen.append(deps)
        return 0

    monkeypatch.setenv("PUBLIC_TOKEN", TOKEN)
    monkeypatch.setattr(cmd_nightly, "run_nightly", capture)
    args = argparse.Namespace(deadline="2026-11-18T06:00:00+01:00", report_dir=str(tmp_path))
    cmd_nightly.nightly(args)
    assert seen[0].aliases is qdrant_aliases


def test_dispatch_builds_its_attempt_with_the_qdrant_index_check(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    attempts: list[Any] = []

    class Reader:
        def __init__(self, token: str) -> None:
            del token

        def statuses(self, sha: str) -> list[dict[str, str]]:
            return []

    job = Job(kind="gate", sha="a" * 40, pr_number=7, tier="pr")

    def fake_dispatch(dispatch: Dispatch, deps: Any) -> int:
        deps.run_gate(job)
        return 0

    def fake_job(attempt: Any, **kwargs: Any) -> str:
        attempts.append(attempt)
        return "x"

    monkeypatch.setenv("PUBLIC_TOKEN", TOKEN)
    monkeypatch.setenv("PRUEFSTAND_MAIN_DIR", str(tmp_path))
    monkeypatch.setenv("PRUEFSTAND_HOME", str(tmp_path))
    monkeypatch.setattr(cmd_dispatch, "PublicRepo", Reader)
    monkeypatch.setattr(cmd_dispatch, "run_dispatch", fake_dispatch)
    monkeypatch.setattr(cmd_dispatch, "run_gate_job", fake_job)
    args = argparse.Namespace(pr=7, actor="dheena18", run_id=1, report_dir=str(tmp_path / "r"))
    cmd_dispatch.dispatch(args)
    assert attempts[0].aliases is qdrant_aliases
