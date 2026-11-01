"""MetricRegistry and evaluate_deterministic (T1.5b S8)."""

from pathlib import Path

import pytest
from testsupport.metric_types import CaseFactory, RespFactory

from pruefstand.core.config.gate import JUDGED_METRICS, KNOWN_METRICS
from pruefstand.core.errors import ConfigError
from pruefstand.core.models.metric import MetricKind, MetricStatus
from pruefstand.metrics.deterministic.record import ErrorRateMetric
from pruefstand.metrics.deterministic.retrieval import ContextRecall
from pruefstand.metrics.registry import MetricRegistry, evaluate_deterministic

DETERMINISTIC = KNOWN_METRICS - JUDGED_METRICS
INTERFACES = Path(__file__).resolve().parents[5] / "docs" / "architecture" / "interfaces.md"


def test_registry_names_equal_known_metrics_minus_judged() -> None:
    names = {m.name for m in MetricRegistry.default().all()}
    assert names == DETERMINISTIC
    assert len(DETERMINISTIC) == 16
    assert names | JUDGED_METRICS == KNOWN_METRICS  # config and registry cannot drift


def test_every_metric_is_deterministic_and_versioned() -> None:
    for metric in MetricRegistry.default().all():
        assert metric.kind is MetricKind.DETERMINISTIC
        assert metric.version


def test_names_are_listed_in_interfaces_section_5() -> None:
    text = INTERFACES.read_text(encoding="utf-8")
    section = text.split("# deterministic (metrics/deterministic", 1)[1].split(
        "# judged (metrics/judged", 1
    )[0]
    for name in DETERMINISTIC:
        assert name in section, name


def test_directions() -> None:
    directions = MetricRegistry.default().directions()
    assert directions["canary_leak"] is False
    assert directions["context_recall"] is True
    assert directions["error_rate"] is False
    assert set(directions) == DETERMINISTIC
    assert directions["citation_grounded"] is True
    assert directions["system_prompt_similarity"] is False
    assert directions["latency_ms"] is False


def test_get_and_unknown_name() -> None:
    registry = MetricRegistry.default()
    assert registry.get("context_recall").name == "context_recall"
    with pytest.raises(ConfigError, match="unknown metric 'nope'"):
        registry.get("nope")


def test_registry_rejects_drift_and_duplicates() -> None:
    class Rogue(ContextRecall):
        name = "not_a_known_metric"

    with pytest.raises(ConfigError, match="not in KNOWN_METRICS"):
        MetricRegistry([Rogue()])
    with pytest.raises(ConfigError, match="duplicate"):
        MetricRegistry([ContextRecall(), ContextRecall()])


def test_evaluate_without_chunks(make_case: CaseFactory, make_resp: RespFactory) -> None:
    registry = MetricRegistry.default()
    values = evaluate_deterministic(
        make_case(), make_resp("Nach § 622 Abs. 2 BGB: ein Monat."), registry.all()
    )
    by_name = {v.metric: v for v in values}
    assert len(values) == len(by_name)  # exactly one value per metric
    assert by_name["context_recall"].status is MetricStatus.NOT_APPLICABLE
    assert by_name["tenant_leak"].status is MetricStatus.NOT_APPLICABLE
    assert by_name["injection_success"].status is MetricStatus.NOT_APPLICABLE
    assert "latency_ms" not in by_name  # D8-30
    assert "error_rate" not in by_name
    assert set(by_name) == DETERMINISTIC - {"latency_ms", "error_rate"}
    assert by_name["citation_recall"].value == 1.0


def test_evaluate_keeps_order_and_skips_record_metrics(
    make_case: CaseFactory, make_resp: RespFactory
) -> None:
    values = evaluate_deterministic(
        make_case(), make_resp("x"), [ErrorRateMetric(), ContextRecall()]
    )
    assert [v.metric for v in values] == ["context_recall"]


def test_default_registry_fails_loudly_when_known_metrics_drifts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "pruefstand.metrics.registry.KNOWN_METRICS", KNOWN_METRICS | {"brand_new_metric"}
    )
    with pytest.raises(ConfigError, match=r"drifted apart.*brand_new_metric"):
        MetricRegistry.default()
