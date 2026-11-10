"""T6.1a (7), D881: ``baseline promote`` needs the run's gate result and refuses failed runs."""

from pathlib import Path

import pytest
from testsupport.pipeline_support import mini_config
from testsupport.promote_support import OTHER, RUN, promote, promoted, stored, write_gate
from typer.testing import CliRunner

from pruefstand.core.enums import GateStatus
from pruefstand.core.errors import StoreIntegrityError
from pruefstand.pipeline.promotion import check_gate_for_promotion
from pruefstand.store.artifacts import ArtifactStore
from pruefstand.store.promote import BaselineRefused


@pytest.fixture
def cli() -> CliRunner:
    return CliRunner()


def test_a_clean_run_with_a_passing_gate_json_is_promoted(cli: CliRunner, tmp_path: Path) -> None:
    run = stored(tmp_path)
    write_gate(run)
    result = promote(cli, tmp_path, run)
    assert result.exit_code == 0, result.output
    assert promoted(tmp_path)


def test_a_missing_gate_json_refuses_main_and_the_flag_does_not_waive_it(
    cli: CliRunner, tmp_path: Path
) -> None:
    run = stored(tmp_path)
    for extra in ((), ("--allow-failed-gate",)):
        result = promote(cli, tmp_path, run, *extra)
        assert result.exit_code == 1
        assert "pruefstand gate" in result.output
    assert not promoted(tmp_path)


def test_a_leak_is_refused_even_when_gate_json_says_pass(cli: CliRunner, tmp_path: Path) -> None:
    run = stored(tmp_path, edits={"tenant_leak": {3: 1.0}})
    write_gate(run)
    result = promote(cli, tmp_path, run)
    assert result.exit_code == 1
    assert "tenant_leak (hard_fail)" in result.output
    assert "--allow-failed-gate" in result.output
    assert not promoted(tmp_path)


def test_an_unverifiable_leak_check_is_refused_and_the_flag_waives_it(
    cli: CliRunner, tmp_path: Path
) -> None:
    run = stored(tmp_path, drop=("tenant_leak",))  # no tenant_leak values at all
    write_gate(run)
    result = promote(cli, tmp_path, run)
    assert result.exit_code == 1
    assert "hard_fail_unverifiable" in result.output
    assert not promoted(tmp_path)
    assert promote(cli, tmp_path, run, "--allow-failed-gate").exit_code == 0
    assert promoted(tmp_path)


def test_a_failed_gate_json_refuses_and_the_flag_waives_it(cli: CliRunner, tmp_path: Path) -> None:
    run = stored(tmp_path)
    write_gate(run, GateStatus.FAIL)
    result = promote(cli, tmp_path, run)
    assert result.exit_code == 1
    assert "FAIL" in result.output
    assert not promoted(tmp_path)
    assert promote(cli, tmp_path, run, "--allow-failed-gate").exit_code == 0
    assert promoted(tmp_path)


def test_a_warning_gate_is_promoted(cli: CliRunner, tmp_path: Path) -> None:
    run = stored(tmp_path)
    write_gate(run, GateStatus.WARN)
    assert promote(cli, tmp_path, run).exit_code == 0


def test_a_gate_json_of_another_run_is_an_integrity_error_the_flag_does_not_waive(
    cli: CliRunner, tmp_path: Path
) -> None:
    run = stored(tmp_path)
    write_gate(run)
    text = (run / "gate.json").read_text(encoding="utf-8").replace(RUN, OTHER)
    (run / "gate.json").write_text(text, encoding="utf-8")
    for extra in ((), ("--allow-failed-gate",)):
        result = promote(cli, tmp_path, run, *extra)
        assert result.exit_code == 3
        assert OTHER in result.output
    assert not promoted(tmp_path)


def test_an_invalid_gate_json_is_an_integrity_error(cli: CliRunner, tmp_path: Path) -> None:
    run = stored(tmp_path)
    (run / "gate.json").write_text("{not json", encoding="utf-8")
    result = promote(cli, tmp_path, run, "--allow-failed-gate")
    assert result.exit_code == 3
    assert "gate" in result.output
    assert not promoted(tmp_path)


def test_a_gate_json_that_is_a_directory_is_an_integrity_error(
    cli: CliRunner, tmp_path: Path
) -> None:
    run = stored(tmp_path)
    (run / "gate.json").mkdir()
    result = promote(cli, tmp_path, run, "--allow-failed-gate")
    assert result.exit_code == 3
    assert "cannot be read" in result.output


def test_a_symlinked_gate_json_is_an_integrity_error(cli: CliRunner, tmp_path: Path) -> None:
    run = stored(tmp_path)
    write_gate(run)
    (tmp_path / "elsewhere.json").write_bytes((run / "gate.json").read_bytes())
    (run / "gate.json").unlink()
    Path(run / "gate.json").symlink_to(tmp_path / "elsewhere.json")
    assert promote(cli, tmp_path, run).exit_code == 3
    assert not promoted(tmp_path)


def test_the_release_anchor_may_lack_a_gate_json_when_it_is_clean(tmp_path: Path) -> None:
    run = stored(tmp_path)
    results = ArtifactStore(tmp_path / "runs").read_run(run).results
    policy = mini_config().gate
    check_gate_for_promotion(
        run, results, policy, ref="release-b0", allow_failed_gate=False, current=None
    )
    with pytest.raises(BaselineRefused, match="pruefstand gate"):
        check_gate_for_promotion(
            run, results, policy, ref="main", allow_failed_gate=False, current=None
        )
    with pytest.raises(BaselineRefused, match="pruefstand gate"):
        check_gate_for_promotion(
            run, results, policy, ref="nightly-b1", allow_failed_gate=True, current=None
        )


def test_the_release_anchor_with_a_leak_is_refused(tmp_path: Path) -> None:
    run = stored(tmp_path, edits={"canary_leak": {0: 1.0}})
    results = ArtifactStore(tmp_path / "runs").read_run(run).results
    with pytest.raises(BaselineRefused, match="canary_leak"):
        check_gate_for_promotion(
            run,
            results,
            mini_config().gate,
            ref="release-b1",
            allow_failed_gate=False,
            current=None,
        )


def test_an_unusable_gate_json_is_an_integrity_error_for_the_release_anchor_too(
    tmp_path: Path,
) -> None:
    run = stored(tmp_path)
    (run / "gate.json").write_text("[]", encoding="utf-8")
    results = ArtifactStore(tmp_path / "runs").read_run(run).results
    with pytest.raises(StoreIntegrityError):
        check_gate_for_promotion(
            run, results, mini_config().gate, ref="release-b0", allow_failed_gate=True, current=None
        )
