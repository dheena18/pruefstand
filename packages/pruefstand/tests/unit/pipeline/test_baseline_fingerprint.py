"""``check_baseline_fingerprint`` and ``pruefstand baseline fingerprint-check`` (D1000)."""

from pathlib import Path

import pytest
from testsupport.builders import fixture_f0, make_record, make_run
from typer.testing import CliRunner

from pruefstand.cli import app
from pruefstand.core.errors import StoreError
from pruefstand.core.models.run import RunArtifacts
from pruefstand.pipeline.baseline_fingerprint import FingerprintCheck, check_baseline_fingerprint
from pruefstand.store.artifacts import ArtifactStore

OLD = "aaaaaaaaaaaa1111"
NEW = "bbbbbbbbbbbb2222"


def stored(root: Path, run_id: str, fingerprint: str) -> Path:
    cases, values = fixture_f0()
    run = make_run(
        run_id, cases, values, records=[make_record(c) for c in cases], eval_fingerprint=fingerprint
    )
    return ArtifactStore(root).write_run(RunArtifacts(results=run, root=root / run_id))


def broken(root: Path, run_id: str) -> Path:
    path = root / run_id
    path.mkdir(parents=True)
    return path


def test_equal_fingerprints_are_comparable(tmp_path: Path) -> None:
    base = stored(tmp_path / "b", "20261102T220000-aaaaaa", OLD)
    cand = stored(tmp_path / "c", "20261102T220001-bbbbbb", OLD)
    assert check_baseline_fingerprint(cand, base) == FingerprintCheck(
        comparable=True, baseline=OLD, candidate=OLD, reason=""
    )


def test_a_changed_fingerprint_is_reported_with_both_values(tmp_path: Path) -> None:
    base = stored(tmp_path / "b", "20261102T220000-aaaaaa", OLD)
    cand = stored(tmp_path / "c", "20261102T220001-bbbbbb", NEW)
    check = check_baseline_fingerprint(cand, base)
    assert not check.comparable
    assert (check.baseline, check.candidate) == (OLD, NEW)
    assert "eval_fingerprint changed" in check.reason


def test_an_unreadable_baseline_is_not_comparable_but_does_not_raise(tmp_path: Path) -> None:
    cand = stored(tmp_path / "c", "20261102T220001-bbbbbb", NEW)
    check = check_baseline_fingerprint(cand, broken(tmp_path / "b", "20261102T220000-aaaaaa"))
    assert not check.comparable
    assert check.baseline == ""
    assert "unreadable" in check.reason


def test_an_unreadable_candidate_raises(tmp_path: Path) -> None:
    base = stored(tmp_path / "b", "20261102T220000-aaaaaa", OLD)
    with pytest.raises(StoreError):
        check_baseline_fingerprint(broken(tmp_path / "c", "20261102T220001-bbbbbb"), base)


def test_the_command_prints_one_line_and_exits_zero_for_both_outcomes(tmp_path: Path) -> None:
    base = stored(tmp_path / "b", "20261102T220000-aaaaaa", OLD)
    same = stored(tmp_path / "c", "20261102T220001-bbbbbb", OLD)
    other = stored(tmp_path / "d", "20261102T220002-cccccc", NEW)
    runner = CliRunner()
    args = ["baseline", "fingerprint-check", "--baseline", str(base), "--candidate"]
    ok = runner.invoke(app, [*args, str(same)])
    assert ok.exit_code == 0, ok.output
    assert ok.stdout.strip() == "comparable"
    changed = runner.invoke(app, [*args, str(other)])
    assert changed.exit_code == 0, changed.output
    assert changed.stdout.strip() == f"changed {OLD[:12]} {NEW[:12]}"


def test_the_command_exits_three_for_an_unreadable_candidate(tmp_path: Path) -> None:
    base = stored(tmp_path / "b", "20261102T220000-aaaaaa", OLD)
    bad = broken(tmp_path / "c", "20261102T220001-bbbbbb")
    result = CliRunner().invoke(
        app, ["baseline", "fingerprint-check", "--baseline", str(base), "--candidate", str(bad)]
    )
    assert result.exit_code == 3, result.output


def test_the_command_prints_unreadable_for_a_broken_baseline(tmp_path: Path) -> None:
    cand = stored(tmp_path / "c", "20261102T220001-bbbbbb", NEW)
    bad = broken(tmp_path / "b", "20261102T220000-aaaaaa")
    result = CliRunner().invoke(
        app, ["baseline", "fingerprint-check", "--baseline", str(bad), "--candidate", str(cand)]
    )
    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == "unreadable"
