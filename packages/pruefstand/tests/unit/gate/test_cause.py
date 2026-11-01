"""Likely cause (``gate.cause``): SPEC §7.4, asserted by code, never by number."""

import pytest

from pruefstand.core.enums import GateStatus
from pruefstand.core.models.gate import CAUSE_MESSAGES, CauseCode, SliceDecision
from pruefstand.gate.cause import likely_cause

PASS, WARN, FAIL = GateStatus.PASS, GateStatus.WARN, GateStatus.FAIL


def row(metric: str, status: GateStatus, dimension: str = "overall", *, gated: bool = True) -> SliceDecision:
    return SliceDecision(
        metric=metric,
        dimension=dimension,
        value=dimension,
        status=status,
        gated=gated,
        baseline_mean=0.8,
        candidate_mean=0.7,
        result=None,
        p_adjusted=None,
        mde=None,
    )


CASES: list[tuple[str, list[SliceDecision], CauseCode | None]] = [
    ("errors", [row("error_rate", FAIL)], "errors"),
    ("errors on WARN", [row("error_rate", WARN)], "errors"),
    ("retrieval context_recall", [row("context_recall", FAIL), row("faithfulness", PASS)], "retrieval"),
    ("retrieval ndcg_at_k", [row("ndcg_at_k", WARN), row("faithfulness", PASS)], "retrieval"),
    ("retrieval via perturbed_all", [row("context_recall", FAIL, "perturbed_all")], "retrieval"),
    ("faithfulness absent counts as stable", [row("context_recall", FAIL)], "retrieval"),
    ("generation faithfulness", [row("faithfulness", FAIL), row("context_recall", PASS)], "generation"),
    ("generation answer_correctness", [row("answer_correctness", WARN)], "generation"),
    ("citation_format recall", [row("citation_recall", FAIL), row("faithfulness", PASS)], "citation_format"),
    ("citation_format grounded", [row("citation_grounded", WARN)], "citation_format"),
    ("language", [row("language_match", FAIL)], "language"),
    ("refusal_policy refusal_correct", [row("refusal_correct", FAIL)], "refusal_policy"),
    ("refusal_policy false_refusal", [row("false_refusal", WARN)], "refusal_policy"),
    ("mixed", [row("context_recall", FAIL), row("language_match", FAIL)], "mixed"),
    ("mixed three", [row("faithfulness", FAIL), row("language_match", WARN), row("false_refusal", FAIL)], "mixed"),
    ("no drop", [row("context_recall", PASS), row("faithfulness", PASS)], None),
    ("empty", [], None),
    ("errors wins over retrieval", [row("error_rate", FAIL), row("context_recall", FAIL)], "errors"),
    ("citation and faithfulness drop is generation", [row("citation_recall", FAIL), row("faithfulness", FAIL)], "generation"),
    ("citation and language drop is mixed", [row("citation_recall", FAIL), row("language_match", FAIL)], "mixed"),
    ("insufficient data is stable", [row("context_recall", GateStatus.INSUFFICIENT_DATA)], None),
    ("informational rows are no cause", [row("context_recall", FAIL, gated=False)], None),
    ("only the perturbed_all of other metrics is not retrieval", [row("faithfulness", FAIL, "perturbed_all")], None),
    ("error_rate passing is no cause", [row("error_rate", PASS), row("language_match", FAIL)], "language"),
]


@pytest.mark.parametrize(("decisions", "expected"), [c[1:] for c in CASES], ids=[c[0] for c in CASES])
def test_likely_cause(decisions: list[SliceDecision], expected: CauseCode | None) -> None:
    assert likely_cause(decisions) == expected


def test_injection_absolute_row_is_not_a_cause() -> None:
    rows = [row("citation_recall", FAIL), row("injection_success", FAIL)]
    assert likely_cause(rows) == "citation_format"


def test_every_code_has_a_message() -> None:
    codes = {"retrieval", "generation", "citation_format", "language", "refusal_policy", "errors", "mixed"}
    assert set(CAUSE_MESSAGES) == codes
    assert CAUSE_MESSAGES["errors"] == "Target errors or timeouts"
    assert all(CAUSE_MESSAGES.values())
