"""T6.1a (7), D881: ``baseline promote`` needs the run's gate result and refuses failed runs."""

from pathlib import Path
from typing import Any

import pytest
from testsupport.builders import fixture_f0, make_record, make_run
from testsupport.pipeline_support import config_file, mini_config
from testsupport.report_builders import gate_report
from testsupport.store_support import FP
from typer.testing import CliRunner, Result

from pruefstand.cli import app
from pruefstand.core.config import BaselineStoreConfig
from pruefstand.core.enums import GateStatus
from pruefstand.core.errors import StoreIntegrityError
from pruefstand.core.models.run import RunArtifacts
from pruefstand.pipeline.promotion import check_gate_for_promotion
from pruefstand.report.json_report import write_gate_json
from pruefstand.store.artifacts import ArtifactStore
from pruefstand.store.baselines_local import LocalDirBaselineStore
from pruefstand.store.promote import BaselineRefused

RUN = "20261102T220001-bbbbbb"
OTHER = "20261102T220009-cccccc"


def stored(
    tmp_path: Path,
    edits: dict[str, dict[int, float]] | None = None,
    drop: tuple[str, ...] = (),
) -> Path:
    cases, values = fixture_f0()
    values = {m: v for m, v in values.items() if m != "faithfulness" and m not in drop}
    for metric, change in (edits or {}).items():
        for index, value in change.items():
            values[metric][index] = value
    records = [make_record(c) for c in cases]
    run = make_run(RUN, cases, values, records=records, eval_fingerprint=FP)
    root = tmp_path / "runs"
    return ArtifactStore(root).write_run(RunArtifacts(results=run, root=root / RUN))


def write_gate(run: Path, status: GateStatus = GateStatus.PASS, **changes: Any) -> None:
    changes = {"hard_fails": (), **changes}
    report = gate_report(candidate_run_id=run.name, status=status, **changes)
    write_gate_json(report, run / "gate.json")


def promote(cli: CliRunner, tmp_path: Path, run: Path, *extra: str, ref: str = "main") -> Result:
    store = BaselineStoreConfig(type="local_dir", path=tmp_path / "store")
    cfg = config_file(tmp_path / "cfg.yaml", mini_config(baseline_store=store))
    args = ["baseline", "promote", "--run", str(run), "--ref", ref, "--config", str(cfg)]
    return cli.invoke(app, [*args, *extra])


def promoted(tmp_path: Path) -> bool:
    return LocalDirBaselineStore(tmp_path / "store").get(FP, "main") is not None


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
    check_gate_for_promotion(run, results, policy, ref="release-b0", allow_failed_gate=False)
    with pytest.raises(BaselineRefused, match="pruefstand gate"):
        check_gate_for_promotion(run, results, policy, ref="main", allow_failed_gate=False)
    with pytest.raises(BaselineRefused, match="pruefstand gate"):
        check_gate_for_promotion(run, results, policy, ref="nightly-b1", allow_failed_gate=True)


def test_the_release_anchor_with_a_leak_is_refused(tmp_path: Path) -> None:
    run = stored(tmp_path, edits={"canary_leak": {0: 1.0}})
    results = ArtifactStore(tmp_path / "runs").read_run(run).results
    with pytest.raises(BaselineRefused, match="canary_leak"):
        check_gate_for_promotion(
            run, results, mini_config().gate, ref="release-b1", allow_failed_gate=False
        )


def test_an_unusable_gate_json_is_an_integrity_error_for_the_release_anchor_too(
    tmp_path: Path,
) -> None:
    run = stored(tmp_path)
    (run / "gate.json").write_text("[]", encoding="utf-8")
    results = ArtifactStore(tmp_path / "runs").read_run(run).results
    with pytest.raises(StoreIntegrityError):
        check_gate_for_promotion(
            run, results, mini_config().gate, ref="release-b0", allow_failed_gate=True
        )
