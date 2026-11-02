"""Every SliceDecision lands in exactly one place of the comment (ui-spec §11.1)."""

from testsupport.report_builders import (
    FAIL,
    INSUFFICIENT,
    PASS,
    WARN,
    absolute_row,
    decision,
    gate_report,
    info_row,
    notable_row,
)
from testsupport.report_render import render

from pruefstand.core.models.gate import GateReport, SliceDecision


def _gated() -> tuple[SliceDecision, ...]:
    return (
        decision("context_recall", status=FAIL),
        decision("faithfulness", status=PASS, ci=(0.0, -0.1, 0.1)),
        decision("citation_recall", dimension="tenant", value="t_warn", status=WARN),
        decision("citation_precision", dimension="tenant", value="t_pass", status=PASS),
        decision("language_match", status=INSUFFICIENT, n_clusters=3),
    )


def _report() -> GateReport:
    absolute = (absolute_row("injection_success", 0.03, WARN), absolute_row("error_rate", 0.0))
    notable = (
        info_row("answer_correctness", "judge_drift", 0.8, 0.78, diff=-0.02),
        notable_row("perturbation", "p_notable", -0.2),
        notable_row("category", "c_quiet", -0.01, notable=False),
    )
    return gate_report(
        hard_fails=(), decisions=_gated(), absolute_checks=absolute, notable_slices=notable
    )


def test_every_decision_is_accounted_for_exactly_once() -> None:
    """One row of each kind, unique names; omissions only by the ui-spec §11.1 rules."""
    out = render(_report())
    expected = {
        "Context recall": 1,
        "Faithfulness": 1,
        "t_warn": 1,
        "t_pass": 0,
        "Language match": 1,
        "Injection success": 1,
        "Error rate": 0,
        "Answer correctness": 1,
        "p_notable": 1,
        "c_quiet": 0,
    }
    for needle, count in expected.items():
        assert out.count(needle) == count, needle
