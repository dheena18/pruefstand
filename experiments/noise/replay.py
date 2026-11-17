"""T6.3 S2b (core): A/A replay of the full gate with a measured sigma_d (SPEC §7.3).

Each synthetic no-op pair is built from the baseline run: per cluster and metric one draw
``e ~ N(0, sigma_d)`` (shared by the cluster's cases; ``|e|`` capped at 1), then every ``ok`` value
``b`` becomes a left value ``l`` and a right value ``r = l + e`` with both in [0, 1] (``l`` is
``b - e/2`` moved just enough to fit). The pair difference is ``e`` exactly, so it is **mean-zero
by construction** even for values at the bounds, where a plain clip of ``b + e`` would create a
systematic drop (D1275). ``latency_ms`` is never shifted; metrics without a sigma_d stay as they
are. Every pair goes through the production ``evaluate_gate`` (left as baseline, right as
candidate); FAIL and WARN-or-FAIL counts carry Wilson 95 % intervals. CPU only; a fixed seed
gives the same counts.
"""

from collections.abc import Iterable, Mapping

import numpy as np
from pydantic import BaseModel, ConfigDict

from pruefstand.core.config.gate import GatePolicy
from pruefstand.core.enums import GateStatus
from pruefstand.core.models.metric import MetricStatus, MetricValue
from pruefstand.core.models.run import RunResults, ScoredCase
from pruefstand.gate.policy import evaluate_gate
from pruefstand.gate.stats import wilson_interval

ALARMS = frozenset({GateStatus.FAIL, GateStatus.WARN, GateStatus.UNSUPPORTED_CONFIG})
UNSHIFTED = frozenset({"latency_ms"})


class ReplayResult(BaseModel):
    """FAIL and WARN-or-FAIL counts of ``n`` A/A pairs, with Wilson 95 % intervals."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    n: int
    fail: int
    warn_or_fail: int
    fail_ci: tuple[float, float]
    warn_or_fail_ci: tuple[float, float]


def split_shift(base: float, shift: float) -> tuple[float, float]:
    """Return ``(left, right)`` in [0, 1] with ``right - left == shift`` (|shift| <= 1).

    Examples:
        >>> split_shift(0.5, 0.2)
        (0.4, 0.6)
        >>> split_shift(1.0, 0.2)
        (0.8, 1.0)
        >>> split_shift(1.0, -0.2)
        (1.0, 0.8)
    """
    low, high = max(0.0, -shift), min(1.0, 1.0 - shift)
    left = min(max(base - shift / 2, low), high)
    return round(left, 12), round(left + shift, 12)


def counts(statuses: Iterable[GateStatus]) -> tuple[int, int, int]:
    """``(n, FAIL, WARN-or-FAIL)``: UNSUPPORTED_CONFIG counts as WARN, INSUFFICIENT_DATA as none."""
    seen = list(statuses)
    return len(seen), sum(s is GateStatus.FAIL for s in seen), sum(s in ALARMS for s in seen)


def _pair_values(value: MetricValue, shift: float | None) -> tuple[MetricValue, MetricValue]:
    if shift is None or value.status is not MetricStatus.OK or value.value is None:
        return value, value
    left, right = split_shift(value.value, shift)
    return value.model_copy(update={"value": left}), value.model_copy(update={"value": right})


def aa_pair(
    baseline: RunResults, sigma: Mapping[str, float], rng: np.random.Generator
) -> tuple[RunResults, RunResults]:
    """One synthetic no-op pair ``(left, right)`` with a mean-zero cluster-level difference."""
    clusters = sorted({case.case.cluster_id for case in baseline.values})
    metrics = sorted(m for m in sigma if m not in UNSHIFTED)
    draws = np.clip(
        rng.normal(0.0, 1.0, size=(len(clusters), len(metrics))) * [sigma[m] for m in metrics],
        -1,
        1,
    )
    shift = {
        (c, m): float(draws[i, j]) for i, c in enumerate(clusters) for j, m in enumerate(metrics)
    }
    left_cases, right_cases = [], []
    for case in baseline.values:
        pairs = [_pair_values(v, shift.get((case.case.cluster_id, v.metric))) for v in case.values]
        left_cases.append(
            ScoredCase.model_construct(case=case.case, values=tuple(p[0] for p in pairs))
        )
        right_cases.append(
            ScoredCase.model_construct(case=case.case, values=tuple(p[1] for p in pairs))
        )
    run_id = baseline.manifest.run_id
    left = RunResults(
        manifest=baseline.manifest.model_copy(update={"run_id": f"{run_id}-aa-left"}),
        records=baseline.records, values=tuple(left_cases),
    )  # fmt: skip
    right = RunResults(
        manifest=baseline.manifest.model_copy(update={"run_id": f"{run_id}-aa-right"}),
        records=baseline.records, values=tuple(right_cases),
    )  # fmt: skip
    return left, right


def replay(
    baseline: RunResults,
    sigma: Mapping[str, float],
    policy: GatePolicy,
    *,
    directions: Mapping[str, bool],
    n: int,
    seed: int,
) -> ReplayResult:
    """Run ``n`` A/A pairs through the production ``evaluate_gate``; count the alarms."""
    rng = np.random.default_rng(seed)
    statuses = []
    for _ in range(n):
        left, right = aa_pair(baseline, sigma, rng)
        statuses.append(evaluate_gate(left, right, policy, rng, directions=directions).status)
    total, fail, alarm = counts(statuses)
    return ReplayResult(
        n=total, fail=fail, warn_or_fail=alarm,
        fail_ci=wilson_interval(fail, total), warn_or_fail_ci=wilson_interval(alarm, total),
    )  # fmt: skip
