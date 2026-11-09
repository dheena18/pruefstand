"""T1.10a / T6.1a (6): ``run_gate`` refuses mixed stacks; an all-cached leak still FAILs."""

from pathlib import Path

import pytest
from testsupport.builders import fixture_f0, make_record, make_run
from testsupport.pipeline_support import mini_config
from testsupport.store_support import write_gate_run

from pruefstand.core.config import GatePolicy, MetricPolicy
from pruefstand.core.enums import GateStatus
from pruefstand.core.errors import GateInputError
from pruefstand.core.models.run import RunArtifacts
from pruefstand.pipeline.gate import run_gate
from pruefstand.store.artifacts import ArtifactStore

BASE_ID, CAND_ID = "20261102T220000-aaaaaa", "20261102T220001-bbbbbb"
FP = "1" * 16
POLICY = GatePolicy(metrics={"context_recall": MetricPolicy(max_drop=0.05)}, n_resamples=500)


def test_run_gate_refuses_a_baseline_of_the_other_stack(tmp_path: Path) -> None:
    base = write_gate_run(tmp_path / "runs", BASE_ID, fp=FP, stack="live")
    cand = write_gate_run(tmp_path / "runs", CAND_ID, fp=FP, stack="a40")
    with pytest.raises(GateInputError, match="never compared"):
        run_gate(cand, base, mini_config(gate=POLICY))
    assert not (cand / "gate.json").exists()


def test_run_gate_accepts_two_runs_of_one_stack(tmp_path: Path) -> None:
    base = write_gate_run(tmp_path / "runs", BASE_ID, fp=FP, stack="live")
    cand = write_gate_run(tmp_path / "runs", CAND_ID, fp=FP, stack="live")
    assert run_gate(cand, base, mini_config(gate=POLICY)).status is GateStatus.PASS


def leaking_all_cached(root: Path) -> Path:
    cases, values = fixture_f0()
    values = {m: v for m, v in values.items() if m != "faithfulness"}
    values["tenant_leak"][3] = 1.0
    run = make_run(
        CAND_ID, cases, values, records=[make_record(c) for c in cases], eval_fingerprint=FP
    )
    counts = {"ok": 120, "cached": 120, "cached_from_base": 120}
    manifest = run.manifest.model_copy(update={"counts": counts})
    done = run.model_copy(update={"manifest": manifest})
    return ArtifactStore(root).write_run(RunArtifacts(results=done, root=root / CAND_ID))


def test_an_all_cached_candidate_with_a_leak_fails_instead_of_exiting_with_an_error(
    tmp_path: Path,
) -> None:
    cand = leaking_all_cached(tmp_path / "runs")
    report = run_gate(cand, None, mini_config(gate=POLICY))
    assert report.status is GateStatus.FAIL
    assert [h.metric for h in report.hard_fails] == ["tenant_leak"]
    assert (cand / "gate.json").is_file()
