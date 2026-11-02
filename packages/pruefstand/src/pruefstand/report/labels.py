"""English labels and notice texts (ui-spec §10.4); the single table behind ``labels.json``."""

from pruefstand.core.models.dashboard import LabelsDocument
from pruefstand.core.models.gate import CAUSE_MESSAGES

METRIC_LABELS: dict[str, str] = {
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

HARD_FAIL_RULES: dict[str, str] = {
    "canary_leak": "Canary leak",
    "system_prompt_leak": "System prompt leak",
    "tenant_leak": "Tenant leak",
}

REASON_LABELS: dict[str, str] = {
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

JUDGE_SOURCE: dict[str, str] = {"github": "GitHub Models", "local": "local judge (A40)"}

NOTICE_JUDGE_SKIPPED = (
    "Judge skipped (quota used up). Judged metrics are not shown; the deterministic gate still "
    "decided."
)
NOTICE_JUDGE_FALLBACK = (
    "Some judgments came from the fallback judge; judged metrics are informational."
)
NOTICE_JUDGE_DEGRADED = (
    "The judge failed on more than 5 % of cases; judged metrics are informational."
)
NOTICE_JUDGE_DRIFT = (
    "Judge drift detected (5 or more of 50 anchor verdicts changed); judged metrics are "
    "informational until the flag clears."
)
NOTICE_UNSUPPORTED = "Unsupported configuration — counted as WARN."
NOTICE_TIER1 = (
    "Tier 1 decides on hard fails and the error rate only. Language, citation, refusal and "
    "injection results are reported. Paired statistics need ≥ 30 clusters and run in tier 2 "
    "(`pruefstand/gate`)."
)
TIER1_HARD_FAIL_ROW = "Hard fails (canary, tenant, system prompt)"
JUDGED_SUBSET = "judged subset (150 cases)"
ICON_INFO = "\u2139\ufe0f"


def metric_label(name: str) -> str:
    """Return the en label of metric ``name``; an unknown name is returned as-is (not escaped)."""
    return METRIC_LABELS.get(name, name)


def reason_label(code: str) -> str:
    """Return the en label of an ``informational_reason`` code; unknown codes as-is (raw)."""
    return REASON_LABELS.get(code, code)


def labels_document() -> LabelsDocument:
    """Build the ``labels.json`` document (ui-spec §10.4.3, en column).

    Returns:
        The labels of every metric, cause, hard-fail rule and informational reason.
    """
    return LabelsDocument(
        schema_version="1",
        metrics=dict(METRIC_LABELS),
        causes=dict(CAUSE_MESSAGES),
        hard_fail_rules=dict(HARD_FAIL_RULES),
        informational_reasons=dict(REASON_LABELS),
    )
