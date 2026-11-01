"""Shared helpers of the ``evaluate_gate`` tests (T1.7): policy P, F0/F1 runs with edits."""

from collections.abc import Callable, Mapping

import numpy as np
from testsupport.builders import fixture_f0, make_run

from pruefstand.core.config import GatePolicy, MetricPolicy
from pruefstand.core.enums import GateStatus
from pruefstand.core.models.gate import GateReport, SliceDecision
from pruefstand.core.models.testcase import TestCase
from pruefstand.gate.policy import evaluate_gate

PASS, WARN, FAIL = GateStatus.PASS, GateStatus.WARN, GateStatus.FAIL
INSUFFICIENT = GateStatus.INSUFFICIENT_DATA
POLICY = GatePolicy(
    metrics={
        "context_recall": MetricPolicy(max_drop=0.05),
        "faithfulness": MetricPolicy(max_drop=0.05),
        "citation_recall": MetricPolicy(max_drop=0.05),
        "language_match": MetricPolicy(max_drop=0.05),
        "error_rate": MetricPolicy(max_value=0.02),
        "injection_success": MetricPolicy(max_value=0.02),
    },
    n_resamples=2000,
)
LOWER = ("error_rate", "injection_success", "canary_leak", "tenant_leak", "system_prompt_leak")
DIRECTIONS = {m: m not in LOWER for m in [*POLICY.metrics, *LOWER]}
PAIRED = [m for m, p in POLICY.metrics.items() if p.max_drop is not None]
Edits = Mapping[str, Mapping[int, float | None]]


def clusters(first: int, last: int) -> list[int]:
    """Case indexes of the clusters ``first``..``last`` (inclusive) of fixture F0."""
    return list(range(2 * first, 2 * last + 2))


def assert_invariant(report: GateReport) -> None:
    """R23 (X5.4): a decision with an informational reason is never gated."""
    for d in (*report.decisions, *report.absolute_checks, *report.notable_slices):
        assert d.informational_reason is None or d.gated is False


def gate(
    edits: Edits | None = None,
    *,
    fixture: Callable[[], tuple[list[TestCase], dict[str, list[float | None]]]] = fixture_f0,
    base_edits: Edits | None = None,
    informational: Mapping[str, str] | None = None,
    counts: Mapping[str, int] | None = None,
    policy: GatePolicy = POLICY,
    directions: Mapping[str, bool] = DIRECTIONS,
    **run_kwargs: object,
) -> GateReport:
    cases, base_values = fixture()

    def edited(e: Edits | None) -> dict[str, list[float | None]]:
        out = {m: list(v) for m, v in base_values.items()}
        for metric, changes in (e or {}).items():
            for index, value in changes.items():
                out[metric][index] = value
        return out

    base = make_run("base", cases, edited(base_edits))
    cand = make_run("cand", cases, edited(edits), counts=counts, **run_kwargs)  # type: ignore[arg-type]
    report = evaluate_gate(
        base, cand, policy, np.random.default_rng(1),
        directions=directions, informational=informational or {},
    )  # fmt: skip
    assert_invariant(report)
    return report


def everywhere(metric: str, value: float, n: int = 120) -> Edits:
    return {metric: dict.fromkeys(range(n), value)}


def row(
    rows: tuple[SliceDecision, ...], metric: str, dimension: str, value: str | None = None
) -> SliceDecision:
    (hit,) = [
        r
        for r in rows
        if (r.metric, r.dimension, r.value) == (metric, dimension, value or dimension)
    ]
    return hit
