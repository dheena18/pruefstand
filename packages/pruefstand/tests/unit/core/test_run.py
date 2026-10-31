from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from pruefstand.core.enums import Category, Difficulty, Lang, Split
from pruefstand.core.models.metric import MetricStatus, MetricValue
from pruefstand.core.models.run import (
    CostSummary,
    RunArtifacts,
    RunManifest,
    RunResults,
    ScoredCase,
)
from pruefstand.core.models.target import CaseRecord
from pruefstand.core.models.testcase import TestCase


def manifest_data(**changes: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "schema_version": "1",
        "run_id": "run-1",
        "created_at": datetime(2026, 11, 2, 22, 0, tzinfo=UTC),
        "pruefstand_version": "0.0.1",
        "git_sha": None,
        "git_ref": None,
        "pr_number": None,
        "target": None,
        "target_fingerprint": "t" * 16,
        "eval_fingerprint": "e" * 16,
        "dataset_name": "pruefstand-de",
        "dataset_version": "v1",
        "splits": [Split.CORE],
        "n_cases": 1,
        "config_hash": "c" * 16,
        "judge_models": {},
        "judge_prompt_versions": {},
        "metric_versions": {"context_recall": "1"},
        "seed": 0,
        "cost": CostSummary(
            usd=0, prompt_tokens=0, completion_tokens=0, gpu_seconds=0, llm_calls=0
        ),
        "duration_s": 1.5,
        "counts": {"ok": 1},
        "complete": True,
        "stop_reason": "completed",
        "stack": "live",
        "workload": "pr",
        "judge_mode": "skipped",
    }
    return {**data, **changes}


def manifest(**changes: Any) -> RunManifest:
    return RunManifest.model_validate(manifest_data(**changes))


def test_complete_iff_completed() -> None:
    with pytest.raises(ValidationError, match="complete"):
        manifest(complete=False, stop_reason="completed")
    with pytest.raises(ValidationError, match="complete"):
        manifest(complete=True, stop_reason="budget_exceeded")
    assert manifest(complete=False, stop_reason="budget_exceeded").complete is False


def test_json_round_trip() -> None:
    m = manifest(counts={"ok": 1, "model_reloads": 0, "upstream_errors": 2}, block=1)
    again = RunManifest.model_validate_json(m.model_dump_json())
    assert again == m
    assert again.counts["upstream_errors"] == 2
    assert again.block == 1


@pytest.mark.parametrize("mode", ["github", "local", "skipped"])
def test_judge_mode_accepted(mode: str) -> None:
    assert manifest(judge_mode=mode).judge_mode == mode


def test_judge_mode_cpu_is_rejected() -> None:
    with pytest.raises(ValidationError, match="judge_mode"):
        manifest(judge_mode="cpu")


def test_defaults() -> None:
    m = manifest()
    assert (m.judge_fallback, m.judge_degraded, m.judge_drift) == (False, False, False)
    assert m.judged_cases == 0
    assert m.judge_serving == {}
    assert m.judge_epoch == 0
    assert m.infra_error is None
    assert m.block is None
    assert m.judged_subset is False
    assert m.stratum == "all"


def test_infra_error_needs_aborted() -> None:
    ok = manifest(infra_error="tunnel_lost: ssh exited", stop_reason="aborted", complete=False)
    assert ok.infra_error is not None
    with pytest.raises(ValidationError, match="infra_error"):
        manifest(infra_error="tunnel_lost: x", stop_reason="budget_exceeded", complete=False)


def test_window_exceeded_kind() -> None:
    ok = manifest(infra_error="window_exceeded: judge", stop_reason="aborted", complete=False)
    assert ok.infra_error == "window_exceeded: judge"
    with pytest.raises(ValidationError, match="infra_error"):
        manifest(infra_error="window_exceeded: judge", stop_reason="completed")


def test_stratum() -> None:
    assert manifest(stratum="refusal").stratum == "refusal"
    assert manifest(stratum="blocks").stratum == "blocks"
    with pytest.raises(ValidationError, match="stratum"):
        manifest(stratum="x")


def test_stack_and_workload_are_restricted() -> None:
    with pytest.raises(ValidationError, match="stack"):
        manifest(stack="gpu")
    with pytest.raises(ValidationError, match="workload"):
        manifest(workload="weekly")


def test_extra_field_is_an_error() -> None:
    with pytest.raises(ValidationError, match="extra"):
        manifest(note="x")


def test_old_json_without_round_12_13_fields_parses() -> None:
    data = manifest_data()
    for key in ("block", "judged_subset", "stratum", "infra_error", "judge_serving", "judge_epoch"):
        data.pop(key, None)
    assert RunManifest.model_validate(data).stratum == "all"


def test_run_artifacts_round_trip() -> None:
    case = TestCase.model_validate(
        {
            "id": "law-1",
            "base_id": "law-1",
            "tenant": "kanzlei_mueller",
            "lang": Lang.DE,
            "question": "Frage?",
            "reference_answer": None,
            "category": Category.FACTUAL,
            "difficulty": Difficulty.EASY,
            "split": Split.CORE,
            "source": "hand",
            "license_config": "own",
            "corpus_version": "v",
        }
    )
    value = MetricValue(
        metric="context_recall", metric_version="1", value=1.0, status=MetricStatus.OK
    )
    record = CaseRecord.model_validate(
        {
            "case_id": "law-1",
            "request": {"tenant_id": "kanzlei_mueller", "question": "Frage?", "request_id": "r"},
            "response": {"answer": "Antwort"},
            "error": None,
            "latency_ms": 3.0,
            "cached": False,
            "attempt": 1,
        }
    )
    results = RunResults(
        manifest=manifest(), records=(record,), values=(ScoredCase(case=case, values=(value,)),)
    )
    artifacts = RunArtifacts(results=results, root=Path("runs/run-1"))
    assert RunArtifacts.model_validate_json(artifacts.model_dump_json()) == artifacts
    assert artifacts.root == Path("runs/run-1")
