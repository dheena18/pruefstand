"""T1.9a: ``pruefstand report --format md`` lists the judge-truncated case ids."""

from pathlib import Path

from testsupport.pipeline_support import mini_config
from testsupport.store_support import gate_run, write_gate_run
from typer.testing import CliRunner

from pruefstand.cli import app
from pruefstand.core.config import GatePolicy, MetricPolicy
from pruefstand.core.models.run import RunArtifacts
from pruefstand.pipeline.gate import run_gate
from pruefstand.store.artifacts import ArtifactStore

BASE_ID, CAND_ID = "20261102T220000-aaaaaa", "20261102T220001-bbbbbb"
FP = "1" * 16
POLICY = GatePolicy(metrics={"context_recall": MetricPolicy(max_drop=0.05)}, n_resamples=500)


def cut_candidate(root: Path) -> tuple[Path, str]:
    """A written candidate whose first case has a truncated judged value."""
    run = gate_run(root, CAND_ID, fp=FP, counts={"ok": 120, "judge_truncated": 1})
    first = run.results.values[0]
    value = first.values[0].model_copy(
        update={"metric": "faithfulness", "details": {"truncated": True}}
    )
    edited = first.model_copy(update={"values": (value, *first.values[1:])})
    values = (edited, *run.results.values[1:])
    results = run.results.model_copy(update={"values": values})
    path = ArtifactStore(root).write_run(RunArtifacts(results=results, root=run.root))
    return path, str(first.case.id)


def test_the_md_report_lists_the_cases_with_a_truncated_judge_input(tmp_path: Path) -> None:
    root = tmp_path / "runs"
    base = write_gate_run(root, BASE_ID, fp=FP)
    cand, case_id = cut_candidate(root)
    run_gate(cand, base, mini_config(gate=POLICY))
    result = CliRunner().invoke(
        app,
        ["report", "--run", str(cand), "--format", "md"],
        env={"NO_COLOR": "1", "COLUMNS": "200", "TERM": "dumb"},
    )
    assert result.exit_code == 0, result.output
    assert "Judge input truncated on 1 case;" in result.output
    assert f"Truncated cases: {case_id}" in result.output
