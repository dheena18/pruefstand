"""Gate policy and metric policy rules (SPEC §5.6, §7.2; interfaces §9)."""

from typing import Any

import pytest
from pydantic import ValidationError

from pruefstand.core.config import KNOWN_METRICS, GatePolicy, MetricPolicy, PruefstandConfig
from pruefstand.core.errors import ConfigError

GEMMA = {"id": "ollama/gemma3:12b", "family": "gemma"}


def build_with_metrics(metrics: dict[str, Any]) -> PruefstandConfig:
    return PruefstandConfig.model_validate(
        {
            "version": 1,
            "target": {"type": "http", "url": "http://localhost:8000"},
            "dataset": "d",
            "splits": ["smoke"],
            "generator_family": "qwen",
            "judge": {"pr": GEMMA, "nightly": GEMMA},
            "gate": {"metrics": metrics},
            "budget": {},
            "runner": {},
            "baseline_store": {"type": "local_dir", "path": "b"},
        }
    )


def test_metric_policy_rejects_a_direction_field() -> None:
    with pytest.raises(ValidationError, match="higher_is_better"):
        MetricPolicy.model_validate({"max_drop": 0.05, "higher_is_better": True})


def test_metric_policy_needs_max_drop_or_max_value() -> None:
    with pytest.raises(ConfigError, match=r"max_drop.*max_value"):
        MetricPolicy()
    assert MetricPolicy(max_value=0.02).max_drop is None
    assert MetricPolicy(max_drop=0.05).confidence == 0.95


@pytest.mark.parametrize("confidence", [1.0, 0.0, -0.1, 1.5])
def test_confidence_must_be_inside_zero_one(confidence: float) -> None:
    with pytest.raises(ValidationError, match="confidence"):
        MetricPolicy(max_drop=0.05, confidence=confidence)


def test_typo_metric_is_named() -> None:
    with pytest.raises(ConfigError, match=r"gate\.metrics\.faithfulnes.*faithfulness"):
        build_with_metrics({"faithfulnes": {"max_drop": 0.05}})


def test_unknown_hard_fail_metric_is_rejected() -> None:
    with pytest.raises(ConfigError, match=r"gate\.hard_fail.*canary_leek"):
        GatePolicy(metrics={}, hard_fail=("canary_leek",))


def test_evidence_recall_is_not_a_known_metric() -> None:
    assert "evidence_recall" not in KNOWN_METRICS
    for name in ("citation_grounded", "system_prompt_similarity", "error_rate", "ndcg_at_k"):
        assert name in KNOWN_METRICS


def test_system_prompt_similarity_is_report_only() -> None:
    for policy in ({"max_drop": 0.05}, {"max_value": 0.5}):
        with pytest.raises(
            ConfigError, match=r"gate\.metrics\.system_prompt_similarity: report-only"
        ):
            GatePolicy.model_validate({"metrics": {"system_prompt_similarity": policy}})


def test_gate_defaults() -> None:
    gate = GatePolicy(metrics={}, slices=())
    assert gate.hard_fail == ("canary_leak", "tenant_leak", "system_prompt_leak")
    assert gate.slices == ()
    assert gate.gated_slices == ("overall", "tenant", "lang", "perturbed_all")
    assert "perturbed_all" in GatePolicy(metrics={}).gated_slices
    assert (gate.alpha, gate.warn_p, gate.min_clusters) == (0.025, 0.10, 30)
    assert (gate.n_resamples, gate.correction, gate.max_error_rate) == (10_000, "holm", 0.02)
    assert GatePolicy(metrics={}).slices == ("category", "perturbation", "tenant", "lang", "tags")


def test_gated_slices_rules() -> None:
    assert GatePolicy(metrics={}, gated_slices=("perturbed_all",)).gated_slices == (
        "perturbed_all",
    )
    with pytest.raises(ConfigError, match=r"gated_slices.*'tenant'"):
        GatePolicy(metrics={}, slices=(), gated_slices=("tenant",))
    only = GatePolicy(metrics={}, slices=("tenant",), gated_slices=("tenant",))
    assert only.gated_slices == ("tenant",)
    with pytest.raises(ConfigError, match="'lang'"):
        GatePolicy(metrics={}, slices=("tenant",), gated_slices=("tenant", "lang"))


def test_alpha_must_be_below_warn_p() -> None:
    with pytest.raises(ConfigError, match="alpha"):
        GatePolicy(metrics={}, alpha=0.2, warn_p=0.1)
    with pytest.raises(ValidationError, match="warn_p"):
        GatePolicy(metrics={}, warn_p=1.0)
    with pytest.raises(ValidationError, match="alpha"):
        GatePolicy(metrics={}, alpha=0.0)


@pytest.mark.parametrize("value", [-0.01, 1.0])
def test_max_error_rate_range(value: float) -> None:
    with pytest.raises(ValidationError, match="max_error_rate"):
        GatePolicy(metrics={}, max_error_rate=value)
    assert GatePolicy(metrics={}, max_error_rate=0.0).max_error_rate == 0.0


def test_metric_both_hard_fail_and_gated_is_rejected() -> None:
    with pytest.raises(ConfigError, match=r"injection_success.*hard_fail"):
        GatePolicy(
            metrics={"injection_success": MetricPolicy(max_value=0.02)},
            hard_fail=("canary_leak", "injection_success"),
        )


def test_shipped_policy_gates_ndcg_next_to_context_recall() -> None:
    gate = GatePolicy(
        metrics={
            "context_recall": MetricPolicy(max_drop=0.05),
            "ndcg_at_k": MetricPolicy(max_drop=0.05),
            "error_rate": MetricPolicy(max_value=0.02),
        }
    )
    assert gate.metrics["ndcg_at_k"].max_drop == 0.05
