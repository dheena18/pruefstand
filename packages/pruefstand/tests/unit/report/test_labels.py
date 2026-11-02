"""``labels_document()``: the en labels of ui-spec §10.4.3 (R9 X5.3, R12 D273)."""

import json
from pathlib import Path
from typing import get_args

import pytest

from pruefstand.core.config import KNOWN_METRICS
from pruefstand.core.models.dashboard import LabelsDocument
from pruefstand.core.models.gate import CAUSE_MESSAGES, CauseCode
from pruefstand.report.labels import labels_document, metric_label, reason_label

EN_METRICS = {
    "context_recall": "Context recall",
    "ndcg_at_k": "nDCG@k",
    "citation_precision": "Citation precision",
    "citation_recall": "Citation recall",
    "citation_f1": "Citation F1",
    "citation_grounded": "Citation grounded",
    "evidence_recall": "Evidence recall",
    "canary_leak": "Canary leak",
    "tenant_leak": "Tenant leak",
    "system_prompt_leak": "System prompt leak",
    "system_prompt_similarity": "System prompt similarity",
    "injection_success": "Injection success",
    "refusal_correct": "Refusal correct",
    "false_refusal": "False refusal",
    "refusal_judged": "Refusal (judged)",
    "language_match": "Language match",
    "error_rate": "Error rate",
    "latency_ms": "Latency (ms)",
    "faithfulness": "Faithfulness",
    "answer_correctness": "Answer correctness",
    "perturbation_consistency": "Perturbation consistency",
}
EN_REASONS = {
    "applicable_clusters<30": "fewer than 30 clusters",
    "refusal_outside_nightly_full": "refusal gated only in nightly full",
    "judge_uncalibrated": "judge not calibrated",
    "judge_degraded": "judge errors above 5 %",
    "judge_drift": "judge drift",
    "tier1_judged": "tier-1 judge (informational)",
    "tier1_deterministic_only": "reported in tier 1",
    "tier1_injection_reported": "injection reported in tier 1",
    "judge_truncated": "judge input truncated",
}


def test_document_is_a_labels_document() -> None:
    doc = labels_document()
    assert isinstance(doc, LabelsDocument)
    assert doc.schema_version == "1"
    assert LabelsDocument.model_validate(doc.model_dump(mode="json")) == doc


def test_metrics_equal_the_en_column() -> None:
    assert labels_document().metrics == EN_METRICS


def test_every_known_metric_cause_and_reason_has_a_label() -> None:
    doc = labels_document()
    assert set(doc.metrics) >= KNOWN_METRICS
    assert set(get_args(CauseCode)) == set(doc.causes)
    assert doc.causes == CAUSE_MESSAGES
    assert doc.informational_reasons == EN_REASONS


def test_hard_fail_rules_is_a_dict_of_en_labels() -> None:
    doc = labels_document()
    assert isinstance(doc.hard_fail_rules, dict)
    assert doc.hard_fail_rules == {
        "canary_leak": "Canary leak",
        "system_prompt_leak": "System prompt leak",
        "tenant_leak": "Tenant leak",
    }


def test_schema_types_hard_fail_rules_as_object_of_strings() -> None:
    schema = LabelsDocument.model_json_schema()
    rules = schema["properties"]["hard_fail_rules"]
    assert rules["type"] == "object"
    assert rules["additionalProperties"] == {"type": "string"}


def test_committed_schema_validates_the_document() -> None:
    path = Path(__file__).resolve().parents[5] / "schemas" / "labels.schema.json"
    committed = json.loads(path.read_text(encoding="utf-8"))
    assert committed == LabelsDocument.model_json_schema()


@pytest.mark.parametrize(
    ("name", "label"), [("context_recall", "Context recall"), ("zz_new", "zz_new")]
)
def test_metric_label_falls_back_to_the_name(name: str, label: str) -> None:
    assert metric_label(name) == label


def test_reason_label_falls_back_to_the_code() -> None:
    assert reason_label("judge_drift") == "judge drift"
    assert reason_label("future_code") == "future_code"
