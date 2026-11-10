"""Review F1, D1120: ``baseline promote`` takes only a gate.json bound to the stored baseline."""

from pathlib import Path
from typing import Any

import pytest
from testsupport.pipeline_support import mini_config
from testsupport.promote_support import OTHER, RUN, promote, promoted, stored, write_gate
from typer.testing import CliRunner

from pruefstand.core.enums import GateStatus
from pruefstand.pipeline.promotion import check_gate_for_promotion
from pruefstand.store.artifacts import ArtifactStore
from pruefstand.store.promote import BaselineRefused


@pytest.fixture
def cli() -> CliRunner:
    return CliRunner()


def first_baseline(cli: CliRunner, tmp_path: Path) -> None:
    """Promote OTHER as the first baseline of (FP, main), gated with ``no_baseline``."""
    base = stored(tmp_path, run_id=OTHER)
    write_gate(base, GateStatus.INSUFFICIENT_DATA)
    assert promote(cli, tmp_path, base).exit_code == 0
    assert promoted(tmp_path, OTHER)


def test_the_first_promote_accepts_the_no_baseline_report(cli: CliRunner, tmp_path: Path) -> None:
    first_baseline(cli, tmp_path)


def test_a_gate_json_of_another_fingerprint_is_an_integrity_error(
    cli: CliRunner, tmp_path: Path
) -> None:
    run = stored(tmp_path)
    write_gate(run, eval_fingerprint="0" * 16)
    for extra in ((), ("--allow-failed-gate",)):
        result = promote(cli, tmp_path, run, *extra)
        assert result.exit_code == 3
        assert "fingerprint" in result.output
    assert not promoted(tmp_path)


@pytest.mark.parametrize("stored_first", [False, True])
def test_a_self_gate_is_refused_and_the_flag_does_not_waive_it(
    cli: CliRunner, tmp_path: Path, *, stored_first: bool
) -> None:
    if stored_first:
        first_baseline(cli, tmp_path)
    run = stored(tmp_path)
    write_gate(run, against=RUN)
    for extra in ((), ("--allow-failed-gate",)):
        result = promote(cli, tmp_path, run, *extra)
        assert result.exit_code == 1
        assert "against itself" in result.output
    assert not promoted(tmp_path)


def test_a_gate_against_the_stored_baseline_is_promoted(cli: CliRunner, tmp_path: Path) -> None:
    first_baseline(cli, tmp_path)
    run = stored(tmp_path)
    write_gate(run, against=OTHER)
    result = promote(cli, tmp_path, run)
    assert result.exit_code == 0, result.output
    assert promoted(tmp_path)


@pytest.mark.parametrize("stored_first", [False, True])
def test_a_gate_against_a_run_that_is_not_the_stored_baseline_is_refused(
    cli: CliRunner, tmp_path: Path, *, stored_first: bool
) -> None:
    if stored_first:
        first_baseline(cli, tmp_path)
    run = stored(tmp_path)
    write_gate(run, against="20261101T220000-ba5e00")
    for extra in ((), ("--allow-failed-gate",)):
        result = promote(cli, tmp_path, run, *extra)
        assert result.exit_code == 1
        assert "20261101T220000-ba5e00" in result.output
    assert not promoted(tmp_path)


def test_a_no_baseline_report_is_refused_once_a_baseline_is_stored(
    cli: CliRunner, tmp_path: Path
) -> None:
    first_baseline(cli, tmp_path)
    run = stored(tmp_path)
    write_gate(run, GateStatus.INSUFFICIENT_DATA)
    result = promote(cli, tmp_path, run)
    assert result.exit_code == 1
    assert "no baseline" in result.output
    assert not promoted(tmp_path)
    assert promote(cli, tmp_path, run, "--allow-failed-gate").exit_code == 0
    assert promoted(tmp_path)


def test_insufficient_data_against_the_stored_baseline_is_refused_and_waivable(
    cli: CliRunner, tmp_path: Path
) -> None:
    first_baseline(cli, tmp_path)
    run = stored(tmp_path)
    write_gate(run, GateStatus.INSUFFICIENT_DATA, against=OTHER)
    result = promote(cli, tmp_path, run)
    assert result.exit_code == 1
    assert "INSUFFICIENT_DATA" in result.output
    assert not promoted(tmp_path)
    assert promote(cli, tmp_path, run, "--allow-failed-gate").exit_code == 0
    assert promoted(tmp_path)


def test_the_guard_compares_with_the_baseline_it_is_given(tmp_path: Path) -> None:
    run = stored(tmp_path)
    write_gate(run, against=OTHER)
    results = ArtifactStore(tmp_path / "runs").read_run(run).results
    policy = mini_config().gate
    kwargs: dict[str, Any] = {"allow_failed_gate": True}
    check_gate_for_promotion(run, results, policy, ref="nightly-b1", current=OTHER, **kwargs)
    with pytest.raises(BaselineRefused, match="not the stored baseline"):
        check_gate_for_promotion(run, results, policy, ref="nightly-b1", current=None, **kwargs)
