"""runs-prune and repo-size (T6.2b S4, D1028): run.json shapes, the 90-night and 14-day rules."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from gate_orchestrator.cmd_nightly import _report
from gate_orchestrator.housekeeping import prune_runs, repo_size_line, runs_to_prune

NOW = datetime(2026, 11, 17, 6, 0, tzinfo=UTC)


def _run(runs: Path, run_id: str, workload: str, age: timedelta) -> Path:
    path = runs / run_id
    path.mkdir(parents=True)
    manifest = {"run_id": run_id, "workload": workload, "created_at": (NOW - age).isoformat()}
    (path / "run.json").write_text(json.dumps(manifest), encoding="utf-8")
    return path


def test_the_newest_90_nights_stay(tmp_path: Path) -> None:
    for i in range(95):
        _run(tmp_path, f"2026{i:04d}-n", "nightly", timedelta(days=95 - i))
    doomed = runs_to_prune(tmp_path, NOW)
    assert [p.name for p in doomed] == [f"2026{i:04d}-n" for i in range(5)]


def test_other_runs_go_after_14_days_and_unreadable_dirs_stay(tmp_path: Path) -> None:
    _run(tmp_path, "pr-old", "pr", timedelta(days=15))
    _run(tmp_path, "pr-new", "pr", timedelta(days=13))
    (tmp_path / "broken").mkdir()
    (tmp_path / "broken" / "run.json").write_text("{", encoding="utf-8")
    assert prune_runs(tmp_path, NOW) == ["pr-old"]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["broken", "pr-new"]


def test_no_runs_dir_prunes_nothing(tmp_path: Path) -> None:
    assert runs_to_prune(tmp_path / "missing", NOW) == []


def test_repo_size_limit() -> None:
    assert repo_size_line(500 * 1024) == (
        True,
        "repo-size: pruefstand-gate is 500 MB (limit 1024 MB)",
    )
    ok, line = repo_size_line(1024 * 1024 + 1)
    assert not ok
    assert line.startswith("repo-size FAILED")


def test_a_failing_housekeeping_step_is_reported_not_raised(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def boom() -> str:
        msg = "disk gone"
        raise OSError(msg)

    _report(boom)
    assert "housekeeping not run: disk gone" in capsys.readouterr().out
