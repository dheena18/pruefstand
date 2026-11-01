"""The PASS / WARN / FAIL / INSUFFICIENT_DATA rule for one (metric, slice) pair (SPEC §7.2)."""

import math

from pruefstand.core.enums import GateStatus
from pruefstand.core.models.gate import BootstrapResult
from pruefstand.gate._validate import fail
from pruefstand.gate.stats import wilson_interval


def decide(
    r: BootstrapResult,
    *,
    max_drop: float,
    p_adjusted: float,
    alpha: float,
    warn_p: float,
    min_clusters: int,
    gated: bool,
) -> GateStatus:
    """Decide one paired comparison: a drop must be significant AND relevant to fail.

    "Significant" means the multiplicity-adjusted p-value is below ``alpha`` (the drop is unlikely
    to be noise). "Relevant" means the observed mean drop is larger than ``max_drop`` (the drop
    matters to a user). Either alone never fails the gate. In order: too few clusters ->
    ``INSUFFICIENT_DATA`` (even for informational slices); not gated -> ``PASS``; significant and
    relevant -> ``FAIL``; ``p_adjusted < warn_p`` and relevant -> ``WARN``; otherwise ``PASS``.

    Args:
        r: Bootstrap result; ``r.mean_diff`` is oriented so negative = worse.
        max_drop: Relevance threshold delta (>= 0).
        p_adjusted: Holm-adjusted p-value of this pair.
        alpha: One-sided significance level of the FAIL rule.
        warn_p: Looser level for WARN.
        min_clusters: Minimum number of clusters for any decision.
        gated: False for informational slices (they never WARN or FAIL).

    Returns:
        The status.

    Raises:
        GateInputError: ``p_adjusted``, ``alpha``, ``warn_p`` or ``max_drop`` is not a finite
            number in its range.

    Examples:
        >>> r = BootstrapResult(mean_diff=-0.06, ci_low=-0.08, ci_high=-0.04, p_value=0.001,
        ...                     method="bootstrap", se=0.01, n_cases=300, n_clusters=300,
        ...                     n_resamples=2000, confidence=0.95)
        >>> kw = dict(max_drop=0.03, alpha=0.025, warn_p=0.10, min_clusters=30, gated=True)
        >>> decide(r, p_adjusted=0.001, **kw).value  # significant and a 6-point drop > 3 points
        'fail'
        >>> decide(r.model_copy(update={"mean_diff": -0.02}), p_adjusted=0.001, **kw).value
        'pass'
    """
    for name, value in (("p_adjusted", p_adjusted), ("alpha", alpha), ("warn_p", warn_p)):
        if not 0.0 <= value <= 1.0:
            fail(f"{name} must lie in [0, 1], got {value!r}")
    if not math.isfinite(max_drop) or max_drop < 0:
        fail("max_drop must be finite and >= 0")
    if r.n_clusters < min_clusters:
        return GateStatus.INSUFFICIENT_DATA
    if not gated:
        return GateStatus.PASS
    relevant = r.mean_diff < -max_drop
    if p_adjusted < alpha and relevant:
        return GateStatus.FAIL
    if p_adjusted < warn_p and relevant:
        return GateStatus.WARN
    return GateStatus.PASS


def decide_absolute(k: int, n: int, *, max_value: float) -> GateStatus:
    """Absolute check on a rate k/n (SPEC §7.2): decide on the Wilson 95 % lower bound.

    ``FAIL`` if the lower bound exceeds ``max_value``; ``WARN`` if it exceeds ``max_value / 2``;
    else ``PASS``. A point estimate above ``max_value`` alone does not warn. ``n = 0`` -> ``PASS``.

    Args:
        k: Number of events (0 <= k <= n).
        n: Number of cases.
        max_value: Largest acceptable rate, in (0, 1].

    Returns:
        The status.

    Raises:
        GateInputError: ``k``/``n`` invalid or ``max_value`` not in (0, 1].

    Examples:
        >>> decide_absolute(3, 120, max_value=0.02).value  # 2.5 % observed, Wilson lower 0.9 %
        'pass'
        >>> decide_absolute(20, 300, max_value=0.02).value  # Wilson lower 4.4 % > 2 %
        'fail'
    """
    if not math.isfinite(max_value) or not 0.0 < max_value <= 1.0:
        fail("max_value must lie in (0, 1]")
    lower, _ = wilson_interval(k, n)
    if n == 0:
        return GateStatus.PASS
    if lower > max_value:
        return GateStatus.FAIL
    if lower > max_value / 2:
        return GateStatus.WARN
    return GateStatus.PASS
