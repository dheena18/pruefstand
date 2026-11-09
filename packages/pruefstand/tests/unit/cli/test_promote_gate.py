"""T6.1a (7), D881: ``baseline promote`` reads the run's gate result and recomputes hard fails."""

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
from pruefstand.core.models.run import RunArtifacts
from pruefstand.report.json_report import write_gate_json
from pruefstand.store.artifacts import ArtifactStore
from pruefstand.store.baselines_local import LocalDirBaselineStore

RUN = "20261102T220001-bbbbbb"
OTHER = "20261102T220009-cccccc"


def stored(
    tmp_path: Path, run_id: str = RUN, edits: dict[str, dict[int, float]] | None = None
) -> Path:
    cases, values = fixture_f0()
    values = {m: v for m, v in values.items() if m != "faithfulness"}
    for metric, change in (edits or {}).items():
        for index, value in change.items():
            values[metric][index] = value
    run = make_run(
        run_id, cases, values, records=[make_record(c) for c in cases], eval_fingerprint=FP
    )
    root = tmp_path / "runs"
    return ArtifactStore(root).write_run(RunArtifacts(results=run, root=root / run_id))


def promote(cli: CliRunner, tmp_path: Path, run: Path, *extra: str) -> Result:
    store = BaselineStoreConfig(type="local_dir", path=tmp_path / "store")
    cfg = config_file(tmp_path / "cfg.yaml", mini_config(baseline_store=store))
    args = ["baseline", "promote", "--run", str(run), "--ref", "main", "--config", str(cfg)]
    return cli.invoke(app, [*args, *extra])


def promoted(tmp_path: Path) -> bool:
    return LocalDirBaselineStore(tmp_path / "store").get(FP, "main") is not None


def write_gate(run: Path, **changes: Any) -> None:
    write_gate_json(gate_report(candidate_run_id=run.name, **changes), run / "gate.json")


@pytest.fixture
def cli() -> CliRunner:
    return CliRunner()


def test_a_clean_run_without_gate_json_is_promoted(cli: CliRunner, tmp_path: Path) -> None:
    result = promote(cli, tmp_path, stored(tmp_path))
    assert result.exit_code == 0, result.output
    assert promoted(tmp_path)


def test_a_run_with_a_hard_fail_is_refused_even_without_gate_json(
    cli: CliRunner, tmp_path: Path
) -> None:
    run = stored(tmp_path, edits={"tenant_leak": {3: 1.0}})
    result = promote(cli, tmp_path, run)
    assert result.exit_code == 1
    assert "tenant_leak" in result.output
    assert "--allow-failed-gate" in result.output
    assert not promoted(tmp_path)


def test_a_failed_gate_json_refuses_the_promotion(cli: CliRunner, tmp_path: Path) -> None:
    run = stored(tmp_path)
    write_gate(run, hard_fails=())  # status FAIL from a gated decision, no hard fail
    result = promote(cli, tmp_path, run)
    assert result.exit_code == 1
    assert "gate" in result.output
    assert not promoted(tmp_path)


def test_the_flag_overrides_a_failed_gate_and_a_hard_fail(cli: CliRunner, tmp_path: Path) -> None:
    run = stored(tmp_path, edits={"tenant_leak": {3: 1.0}})
    write_gate(run)
    result = promote(cli, tmp_path, run, "--allow-failed-gate")
    assert result.exit_code == 0, result.output
    assert promoted(tmp_path)


def test_a_passing_gate_json_is_promoted(cli: CliRunner, tmp_path: Path) -> None:
    run = stored(tmp_path)
    write_gate(run, status=GateStatus.WARN, hard_fails=())
    assert promote(cli, tmp_path, run).exit_code == 0
    assert promoted(tmp_path)


def test_a_gate_json_of_another_run_is_refused_and_the_flag_does_not_waive_it(
    cli: CliRunner, tmp_path: Path
) -> None:
    run = stored(tmp_path)
    write_gate(run, status=GateStatus.PASS, hard_fails=())
    text = (run / "gate.json").read_text(encoding="utf-8").replace(RUN, OTHER)
    (run / "gate.json").write_text(text, encoding="utf-8")
    for extra in ((), ("--allow-failed-gate",)):
        result = promote(cli, tmp_path, run, *extra)
        assert result.exit_code == 1
        assert OTHER in result.output
    assert not promoted(tmp_path)


def test_an_unreadable_gate_json_is_refused(cli: CliRunner, tmp_path: Path) -> None:
    run = stored(tmp_path)
    (run / "gate.json").write_text("{not json", encoding="utf-8")
    result = promote(cli, tmp_path, run, "--allow-failed-gate")
    assert result.exit_code == 1
    assert "gate.json" in result.output
    assert not promoted(tmp_path)
