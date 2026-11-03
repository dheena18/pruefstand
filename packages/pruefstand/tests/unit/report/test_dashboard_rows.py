"""Row builders of ``export-dashboard`` on hand-made decisions (ui-spec §11.1) and real runs."""

from pathlib import Path

import pytest
from testsupport.dashboard_export_support import RAW, roles

from pruefstand.core.enums import GateStatus
from pruefstand.core.models.dashboard import MAX_SHARD_CASES
from pruefstand.core.models.gate import BootstrapResult, GateReport, SliceDecision
from pruefstand.report._dashboard_rows import (
    case_shards,
    error_class,
    failing_ids,
    index_entry,
    slice_rows,
)
from pruefstand.store.artifacts import ArtifactStore


def _decision(metric: str, **update: object) -> SliceDecision:
    result = BootstrapResult(
        mean_diff=-0.07, ci_low=-0.1, ci_high=-0.04, p_value=0.01, method="bootstrap", se=0.02,
        n_cases=40, n_clusters=35, n_resamples=1000, confidence=0.95,
    )  # fmt: skip
    base: dict[str, object] = {
        "metric": metric, "dimension": "overall", "value": "all", "status": GateStatus.PASS,
        "gated": True, "baseline_mean": 0.9, "candidate_mean": 0.83, "result": result,
        "p_adjusted": 0.02, "mde": 0.05, "max_drop": 0.05, "max_value": None, "n_clusters": 35,
    }  # fmt: skip
    return SliceDecision.model_validate({**base, **update})


def _report(**update: object) -> GateReport:
    plain = _decision("context_recall")
    info = _decision("faithfulness", gated=False, informational_reason="tier1_judged")
    absolute = _decision("error_rate", result=None, max_drop=None, max_value=0.02, mde=None)
    notable = _decision("ndcg_at_k", dimension="tenant", value="a", notable=True, gated=False)
    base: dict[str, object] = {
        "schema_version": "1", "status": GateStatus.PASS,
        "baseline_run_id": "20261103T000000-aaaaaa",
        "candidate_run_id": "20261103T010000-bbbbbb", "eval_fingerprint": "f", "hard_fails": (),
        "decisions": (plain, info), "absolute_checks": (absolute,), "notable_slices": (notable,),
        "likely_cause": None, "top_failing_cases": (),
    }  # fmt: skip
    return GateReport.model_validate({**base, **update})


def test_one_row_per_decision_with_the_kind_rule() -> None:
    rows = slice_rows(_report()).rows
    assert [(r.metric, r.kind) for r in rows] == [
        ("context_recall", "decision"),
        ("faithfulness", "informational"),
        ("error_rate", "absolute"),
        ("ndcg_at_k", "informational"),
    ]


def test_values_are_copied_and_ci_fields_are_none_without_a_result() -> None:
    plain, _, absolute, _ = slice_rows(_report()).rows
    assert (plain.mean_diff, plain.ci_low, plain.ci_high) == (-0.07, -0.1, -0.04)
    assert (plain.max_drop, plain.mde, plain.n_clusters) == (0.05, 0.05, 35)
    assert (absolute.mean_diff, absolute.ci_low, absolute.ci_high) == (None, None, None)
    assert absolute.max_value == 0.02
    assert slice_rows(_report()).run_id == "20261103T010000-bbbbbb"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (None, None),
        ("timeout after 60 s", "TimeoutError"),
        ("ConnectError: boom, tenant secret", "ConnectError"),
        ("HTTP 500 from the target: <html>", "TargetError"),
    ],
)
def test_error_text_is_reduced_to_a_class(text: str | None, expected: str | None) -> None:
    assert error_class(text) == expected


def test_failing_ids_are_top_failing_plus_hard_fail_cases() -> None:
    assert failing_ids(None) == frozenset()
    assert failing_ids(_report(top_failing_cases=("c1", "c2"))) == {"c1", "c2"}


def _results(name: str):  # type: ignore[no-untyped-def]  # test helper, the model type is not needed
    return ArtifactStore(RAW).read_run(RAW / name).results


def test_shards_are_ordered_failing_first_then_case_id_and_sized() -> None:
    results = _results(roles()["F-T1"])
    ids = sorted(s.case.id for s in results.values)
    shards = case_shards(results, {ids[-1]}, size=7)
    assert [s.shard for s in shards] == list(range(len(shards)))
    assert {s.n_shards for s in shards} == {len(shards)}
    assert all(len(s.cases) <= 7 for s in shards)
    flat = [c for s in shards for c in s.cases]
    assert flat[0].case_id == ids[-1]
    assert flat[0].failing is True
    assert [c.case_id for c in flat[1:]] == ids[:-1]
    assert MAX_SHARD_CASES == 500


def test_a_run_without_cases_has_one_empty_shard_zero() -> None:
    results = _results(roles()["F-T1"])
    empty = results.model_copy(update={"records": (), "values": ()})
    (shard,) = case_shards(empty, ())
    assert (shard.shard, shard.n_shards, shard.cases) == (0, 1, ())


def test_case_fields_are_copied_from_the_run() -> None:
    results = _results(roles()["F-T1"])
    shard = case_shards(results, ())[0]
    by_id = {s.case.id: s for s in results.values}
    records = {r.case_id: r for r in results.records}
    for case in shard.cases:
        scored, record = by_id[case.case_id], records[case.case_id]
        assert case.lang == scored.case.lang
        assert case.metric_status == {v.metric: v.status for v in scored.values}
        assert case.citations == (record.response.citations if record.response else ())
        assert len(case.retrieved_chunk_ids) == len(case.retrieved_chunk_tenant_ids)


def test_index_entry_has_no_gate_fields_without_a_gate() -> None:
    manifest = _results(roles()["F-T1"]).manifest
    entry = index_entry(manifest, None)
    assert (entry.status, entry.baseline_run_id, entry.no_baseline) == (None, None, False)
    assert entry.cost_usd == manifest.cost.usd
    assert Path(RAW).is_dir()
