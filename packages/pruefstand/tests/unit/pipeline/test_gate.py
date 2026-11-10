"""``run_gate`` and the ``informational`` mapping of the pipeline (T1.10 S3, S4b)."""

import json
from pathlib import Path
from typing import Any

import pytest
from testsupport.builders import fixture_f0, make_record, make_run
from testsupport.pipeline_support import mini_config
from testsupport.run_builders import make_manifest

from pruefstand.core.config import GatePolicy, MetricPolicy
from pruefstand.core.enums import GateStatus, Split
from pruefstand.core.errors import GateInputError, StoreError
from pruefstand.core.fingerprint import eval_fingerprint
from pruefstand.core.models.gate import GateReport
from pruefstand.core.models.run import RunArtifacts, RunManifest
from pruefstand.pipeline import gate as gate_module
from pruefstand.pipeline.fingerprints import build_eval_fingerprint, judge_facts
from pruefstand.pipeline.gate import informational_mapping, run_gate
from pruefstand.store.artifacts import ArtifactStore

POLICY = GatePolicy(
    metrics={
        "context_recall": MetricPolicy(max_drop=0.05),
        "faithfulness": MetricPolicy(max_drop=0.05),
        "citation_recall": MetricPolicy(max_drop=0.05),
        "refusal_correct": MetricPolicy(max_drop=0.10),
        "false_refusal": MetricPolicy(max_drop=0.03),
        "language_match": MetricPolicy(max_drop=0.03),
        "injection_success": MetricPolicy(max_value=0.02),
        "error_rate": MetricPolicy(max_value=0.02),
    }
)


def manifests(**changes: Any) -> tuple[RunManifest, RunManifest]:
    base = make_manifest(run_id="20261102T220000-aaaaaa", **changes)
    cand = make_manifest(run_id="20261102T220001-bbbbbb", **changes)
    return base, cand


# --- informational mapping (S4b) ---------------------------------------------------------------


def test_tier_one_decides_on_hard_fails_and_error_rate_only() -> None:
    base, cand = manifests(stack="live", workload="pr")
    info = informational_mapping(base, cand, POLICY)
    assert info["faithfulness"] == "tier1_judged"
    for metric in ("language_match", "citation_recall", "refusal_correct", "context_recall"):
        assert info[metric] == "tier1_deterministic_only"
    assert info["false_refusal"] == "tier1_deterministic_only"
    assert info["injection_success"] == "tier1_injection_reported"
    assert "error_rate" not in info


def test_tier_one_marks_every_judged_metric_even_when_the_nightly_runs_it() -> None:
    base, cand = manifests(stack="live", workload="nightly", splits=(Split.FULL,))
    info = informational_mapping(base, cand, POLICY)
    assert info["faithfulness"] == "tier1_judged"
    assert info["refusal_correct"] == "tier1_deterministic_only"  # first match wins


def test_a_degraded_baseline_judge_makes_judged_metrics_informational() -> None:
    base, cand = manifests(stack="a40")
    base = base.model_copy(update={"judge_degraded": True})
    info = informational_mapping(base, cand, POLICY)
    assert info["faithfulness"] == "judge_degraded"
    assert "context_recall" not in info


def test_a_judge_fallback_on_either_run_makes_every_judged_metric_informational() -> None:
    base, cand = manifests(stack="a40")
    info = informational_mapping(base, cand.model_copy(update={"judge_fallback": True}), POLICY)
    assert info["faithfulness"] == "judge_fallback"
    assert "context_recall" not in info  # deterministic metrics still gate
    info = informational_mapping(base.model_copy(update={"judge_fallback": True}), cand, POLICY)
    assert info["faithfulness"] == "judge_fallback"
    both = cand.model_copy(update={"judge_fallback": True, "judge_degraded": True})
    assert informational_mapping(base, both, POLICY)["faithfulness"] == "judge_fallback"


def test_degraded_wins_over_drift() -> None:
    base, cand = manifests(stack="a40")
    drift = cand.model_copy(update={"judge_drift": True, "counts": {"judge_truncated": 9}})
    assert informational_mapping(base, drift, POLICY)["faithfulness"] == "judge_drift"
    both = drift.model_copy(update={"judge_degraded": True})
    assert informational_mapping(base, both, POLICY)["faithfulness"] == "judge_degraded"


def test_candidate_truncation_never_makes_a_judged_metric_informational() -> None:
    base, cand = manifests(stack="a40")
    cand = cand.model_copy(update={"judged_cases": 100, "counts": {"judge_truncated": 60}})
    assert "faithfulness" not in informational_mapping(base, cand, POLICY)  # D815


def test_refusal_correct_is_gated_only_in_the_nightly_full_run() -> None:
    base, cand = manifests(stack="a40", workload="pr")
    info = informational_mapping(base, cand, POLICY)
    assert info["refusal_correct"] == "refusal_outside_nightly_full"
    assert "false_refusal" not in info
    base, cand = manifests(stack="a40", workload="nightly", splits=(Split.FULL,))
    info = informational_mapping(base, cand, POLICY)
    assert "refusal_correct" not in info
    assert "false_refusal" not in info
    base, cand = manifests(stack="a40", workload="nightly", splits=(Split.CORE,))
    assert (
        informational_mapping(base, cand, POLICY)["refusal_correct"]
        == "refusal_outside_nightly_full"
    )


# --- fingerprint inputs (X3.3) -----------------------------------------------------------------


def _fingerprint(stack: str, serving: dict[str, str], epoch: int) -> str:
    cfg = mini_config(gate=POLICY)
    facts = judge_facts(cfg, stack=stack, tier="pr", serving=serving, epoch=epoch)  # type: ignore[arg-type]  # Literal in the helper
    return build_eval_fingerprint(
        facts,
        name="mini",
        version="v0",
        corpus_version="c",
        splits=(Split.SMOKE,),
        metric_versions={"context_recall": "1"},
    )


def test_a_gated_judge_serving_or_epoch_change_changes_the_fingerprint() -> None:
    serving = {"faithfulness": "ollama 0.6.1 Q4_K_M abc"}
    base = _fingerprint("a40", serving, 1)
    assert _fingerprint("a40", {"faithfulness": "ollama 0.6.2 Q4_K_M abc"}, 1) != base
    assert _fingerprint("a40", serving, 2) != base
    assert _fingerprint("a40", serving, 1) == base


def test_tier_one_passes_no_judges_to_the_fingerprint() -> None:
    cfg = mini_config(gate=POLICY)
    facts = judge_facts(cfg, stack="live", tier="pr", serving={"faithfulness": "x"}, epoch=3)
    assert (facts.models, facts.prompt_versions, facts.serving) == ({}, {}, {})
    assert facts.epoch == 3
    expected = eval_fingerprint(
        dataset_name="mini",
        dataset_version="v0",
        splits=(Split.SMOKE,),
        judge_models={},
        judge_prompt_versions={},
        judge_serving={},
        judge_epoch=3,
        metric_versions={"context_recall": "1"},
        corpus_version="c",
    )
    assert _fingerprint("live", {"faithfulness": "x"}, 3) == expected


def test_only_gated_judged_metrics_enter_the_judge_models() -> None:
    cfg = mini_config(gate=POLICY)
    facts = judge_facts(cfg, stack="a40", tier="nightly")
    assert facts.models == {"faithfulness": cfg.judge.nightly.id}
    per_metric = cfg.judge.model_copy(update={"per_metric": {"faithfulness": cfg.judge.pr}})
    cfg2 = cfg.model_copy(update={"judge": per_metric})
    assert judge_facts(cfg2, stack="a40", tier="nightly").models == {
        "faithfulness": cfg.judge.pr.id
    }


# --- run_gate ----------------------------------------------------------------------------------

GATE_POLICY = GatePolicy(
    metrics={
        "context_recall": MetricPolicy(max_drop=0.05),
        "citation_recall": MetricPolicy(max_drop=0.05),
        "language_match": MetricPolicy(max_drop=0.03),
        "error_rate": MetricPolicy(max_value=0.02),
    },
    n_resamples=500,
)


def stored(root: Path, run_id: str, **run_kwargs: object) -> Path:
    cases, values = fixture_f0()
    values = {m: v for m, v in values.items() if m != "faithfulness"}
    edits = run_kwargs.pop("edits", {})
    for metric, change in dict(edits).items():  # type: ignore[call-overload]  # test-only mapping
        for index, value in change.items():
            values[metric][index] = value
    records = [make_record(c) for c in cases]
    run = make_run(run_id, cases, values, records=records, **run_kwargs)  # type: ignore[arg-type]  # kwargs forwarded
    return ArtifactStore(root).write_run(RunArtifacts(results=run, root=root / run_id))


def test_run_gate_writes_gate_json_next_to_the_candidate(tmp_path: Path) -> None:
    base = stored(tmp_path, "20261102T220000-aaaaaa")
    cand = stored(tmp_path, "20261102T220001-bbbbbb")
    report = run_gate(cand, base, mini_config(gate=GATE_POLICY))
    assert report.status is GateStatus.PASS
    on_disk = GateReport.model_validate_json((cand / "gate.json").read_text(encoding="utf-8"))
    assert on_disk == report
    assert report.baseline_run_id == "20261102T220000-aaaaaa"


def test_run_gate_is_deterministic_for_one_seed(tmp_path: Path) -> None:
    base = stored(tmp_path, "20261102T220000-aaaaaa")
    cand = stored(tmp_path, "20261102T220001-bbbbbb", edits={"context_recall": {0: 0.0, 1: 0.0}})
    cfg = mini_config(gate=GATE_POLICY)
    first, second = run_gate(cand, base, cfg), run_gate(cand, base, cfg)
    assert first == second


def test_run_gate_finds_a_hard_fail(tmp_path: Path) -> None:
    base = stored(tmp_path, "20261102T220000-aaaaaa")
    cand = stored(tmp_path, "20261102T220001-bbbbbb", edits={"tenant_leak": {3: 1.0}})
    report = run_gate(cand, base, mini_config(gate=GATE_POLICY))
    assert report.status is GateStatus.FAIL
    assert [h.metric for h in report.hard_fails] == ["tenant_leak"]


def test_a_policy_metric_without_a_registry_direction_is_a_gate_input_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # a calibrated judge: with T5.4's passed: false the judged metric would be informational first
    monkeypatch.setattr(gate_module, "judges_uncalibrated", lambda *_: False)
    base = stored(tmp_path, "20261102T220000-aaaaaa")
    cand = stored(tmp_path, "20261102T220001-bbbbbb")
    with pytest.raises(GateInputError, match="faithfulness"):
        run_gate(cand, base, mini_config(gate=POLICY))


def test_fingerprint_mismatch_is_a_gate_input_error(tmp_path: Path) -> None:
    base = stored(tmp_path, "20261102T220000-aaaaaa", eval_fingerprint="one")
    cand = stored(tmp_path, "20261102T220001-bbbbbb", eval_fingerprint="two")
    with pytest.raises(GateInputError):
        run_gate(cand, base, mini_config(gate=GATE_POLICY))


def test_missing_run_directory_is_a_store_error(tmp_path: Path) -> None:
    cand = stored(tmp_path, "20261102T220001-bbbbbb")
    with pytest.raises(StoreError):
        run_gate(cand, tmp_path / "missing", mini_config(gate=GATE_POLICY))


def test_without_a_baseline_the_report_says_no_baseline(tmp_path: Path) -> None:
    cand = stored(tmp_path, "20261102T220001-bbbbbb")
    report = run_gate(cand, None, mini_config(gate=GATE_POLICY))
    assert report.status is GateStatus.INSUFFICIENT_DATA
    assert report.no_baseline is True
    assert report.baseline_run_id is None
    assert report.eval_fingerprint == "ef-test"
    assert (cand / "gate.json").is_file()


def test_without_a_baseline_a_hard_fail_still_fails(tmp_path: Path) -> None:
    cand = stored(tmp_path, "20261102T220001-bbbbbb", edits={"canary_leak": {0: 1.0}})
    report = run_gate(cand, None, mini_config(gate=GATE_POLICY))
    assert report.status is GateStatus.FAIL
    assert report.no_baseline is True
    assert [h.metric for h in report.hard_fails] == ["canary_leak"]


def test_gate_json_is_valid_json_with_sorted_keys(tmp_path: Path) -> None:
    base = stored(tmp_path, "20261102T220000-aaaaaa")
    cand = stored(tmp_path, "20261102T220001-bbbbbb")
    run_gate(cand, base, mini_config(gate=GATE_POLICY))
    data = json.loads((cand / "gate.json").read_text(encoding="utf-8"))
    assert list(data) == sorted(data)


@pytest.mark.parametrize("how", ["aborted", "budget_exceeded", "corpus_mismatch"])
def test_an_incomplete_candidate_without_a_baseline_is_a_gate_input_error(
    tmp_path: Path, how: str
) -> None:
    cases, values = fixture_f0()
    values = {m: v for m, v in values.items() if m != "faithfulness"}
    run = make_run(
        "20261102T220001-bbbbbb",
        cases,
        values,
        records=[make_record(c) for c in cases],
        complete=False,
        counts={"corpus_mismatch": 1} if how == "corpus_mismatch" else None,
    )
    if how == "budget_exceeded":
        manifest = run.manifest.model_copy(update={"stop_reason": "budget_exceeded"})
        run = run.model_copy(update={"manifest": manifest})
    root = tmp_path / "runs"
    cand = ArtifactStore(root).write_run(RunArtifacts(results=run, root=root / run.manifest.run_id))
    with pytest.raises(GateInputError, match="complete"):
        run_gate(cand, None, mini_config(gate=GATE_POLICY))
    assert not (cand / "gate.json").exists()
