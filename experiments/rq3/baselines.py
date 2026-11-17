"""RQ3 comparison gates (T7.2 S2): the naive mean gate and the no-slices gate.

Both decide on the same baseline/candidate runs as production ``evaluate_gate`` (variant 1), so only
the decision rule differs (``PREREGISTRATION.md``):

* **naive mean gate** (variant 2): FAIL when the overall mean of any gated paired metric drops by
  more than its ``max_drop`` (no pairing, no bootstrap, no WARN); hard fails and absolute checks
  still apply, taken from the production report of the same runs, so leaks are not the
  differentiator;
* **no-slices gate** (variant 3): production statistics on the ``overall`` slice only.
"""

import math
from collections.abc import Mapping

import numpy as np

from pruefstand.core.config.gate import GatePolicy
from pruefstand.core.enums import GateStatus
from pruefstand.core.models.gate import GateReport
from pruefstand.core.models.metric import MetricStatus
from pruefstand.core.models.run import RunResults
from pruefstand.gate.policy import evaluate_gate


def overall_mean(run: RunResults, metric: str) -> float | None:
    """Mean of the ``ok`` values of ``metric`` over all cases (None: no ``ok`` value).

    Examples:
        >>> from testsupport.builders import fixture_f0, make_run
        >>> cases, values = fixture_f0()
        >>> round(overall_mean(make_run("r", cases, values), "context_recall"), 3) > 0
        True
    """
    numbers = [
        v.value
        for case in run.values
        for v in case.values
        if v.metric == metric and v.status is MetricStatus.OK and v.value is not None
    ]
    return math.fsum(numbers) / len(numbers) if numbers else None


def naive_gate(
    production: GateReport,
    baseline: RunResults,
    candidate: RunResults,
    policy: GatePolicy,
    *,
    directions: Mapping[str, bool],
) -> GateStatus:
    """Variant 2: hard fails and absolute checks as in production, else a plain mean-drop rule.

    Args:
        production: ``evaluate_gate`` on the same runs (its hard fails and absolute checks).
        baseline: Baseline run.
        candidate: Candidate run.
        policy: Gate policy; every metric with a ``max_drop`` is checked on ``overall``.
        directions: metric -> ``higher_is_better``.

    Returns:
        ``FAIL`` or ``PASS``.
    """
    if production.hard_fails or any(
        c.status is GateStatus.FAIL for c in production.absolute_checks
    ):
        return GateStatus.FAIL
    for metric, rule in policy.metrics.items():
        if rule.max_drop is None:
            continue
        base, cand = overall_mean(baseline, metric), overall_mean(candidate, metric)
        if base is None or cand is None:
            continue
        drop = base - cand if directions[metric] else cand - base
        if drop > rule.max_drop:
            return GateStatus.FAIL
    return GateStatus.PASS


def no_slice_gate(
    baseline: RunResults,
    candidate: RunResults,
    policy: GatePolicy,
    rng: np.random.Generator,
    *,
    directions: Mapping[str, bool],
    informational: Mapping[str, str] | None = None,
) -> GateReport:
    """Variant 3: production ``evaluate_gate`` with ``gated_slices`` reduced to ``overall``."""
    overall_only = policy.model_copy(update={"gated_slices": ("overall",)})
    return evaluate_gate(
        baseline,
        candidate,
        overall_only,
        rng,
        directions=directions,
        informational=informational or {},
    )
