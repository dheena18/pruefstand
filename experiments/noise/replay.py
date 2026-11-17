"""T6.3 S2b (core): A/A replay of the full gate with a measured sigma_d (SPEC §7.3).

Each synthetic no-op pair is the baseline run against a copy of itself whose ``ok`` values move
by a cluster-level shift drawn from N(0, sigma_d of the metric) (one draw per cluster and
metric, shared by the cluster's cases, values clipped to [0, 1]; ``latency_ms`` is left alone).
Every pair goes through the production ``evaluate_gate``; the FAIL and WARN-or-FAIL rates with
Wilson 95 % intervals are the no-op false-block and false-warn estimates. Run once with
sigma_d(no-op) (the checked arm) and once with sigma_d(churn). CPU only; a fixed seed gives the
same counts.
"""

from collections.abc import Mapping

import numpy as np
from pydantic import BaseModel, ConfigDict

from pruefstand.core.config.gate import GatePolicy
from pruefstand.core.enums import GateStatus
from pruefstand.core.models.metric import MetricStatus, MetricValue
from pruefstand.core.models.run import RunResults, ScoredCase
from pruefstand.gate.policy import evaluate_gate
from pruefstand.gate.stats import wilson_interval


class ReplayResult(BaseModel):
    """FAIL and WARN-or-FAIL counts of ``n`` A/A pairs, with Wilson 95 % intervals."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    n: int
    fail: int
    warn_or_fail: int
    fail_ci: tuple[float, float]
    warn_or_fail_ci: tuple[float, float]


def _shifted(value: MetricValue, shift: float) -> MetricValue:
    if value.status is not MetricStatus.OK or value.value is None or value.metric == "latency_ms":
        return value
    moved = min(max(value.value + shift, 0.0), 1.0)
    return value.model_copy(update={"value": moved})


def noop_candidate(
    baseline: RunResults, sigma: Mapping[str, float], rng: np.random.Generator
) -> RunResults:
    """A synthetic no-op candidate: per cluster and metric, one N(0, sigma_d) shift of its values.

    Metrics without a sigma_d entry stay unchanged (e.g. hard-fail and deterministic leak checks).
    """
    clusters = sorted({case.case.cluster_id for case in baseline.values})
    metrics = sorted(sigma)
    draws = rng.normal(0.0, 1.0, size=(len(clusters), len(metrics)))
    shift = {
        (cluster, metric): float(draws[i, j]) * sigma[metric]
        for i, cluster in enumerate(clusters)
        for j, metric in enumerate(metrics)
    }
    values = tuple(
        ScoredCase.model_construct(
            case=case.case,
            values=tuple(
                _shifted(v, shift[(case.case.cluster_id, v.metric)]) if v.metric in sigma else v
                for v in case.values
            ),
        )
        for case in baseline.values
    )
    manifest = baseline.manifest.model_copy(update={"run_id": f"{baseline.manifest.run_id}-aa"})
    return RunResults(manifest=manifest, records=baseline.records, values=values)


def replay(
    baseline: RunResults,
    sigma: Mapping[str, float],
    policy: GatePolicy,
    *,
    directions: Mapping[str, bool],
    n: int,
    seed: int,
) -> ReplayResult:
    """Run ``n`` A/A pairs through ``evaluate_gate``; count FAIL and WARN-or-FAIL.

    ``UNSUPPORTED_CONFIG`` counts as WARN; ``INSUFFICIENT_DATA`` is neither.
    """
    rng = np.random.default_rng(seed)
    fail = warn_or_fail = 0
    for _ in range(n):
        candidate = noop_candidate(baseline, sigma, rng)
        status = evaluate_gate(baseline, candidate, policy, rng, directions=directions).status
        fail += status is GateStatus.FAIL
        warn_or_fail += status in (GateStatus.FAIL, GateStatus.WARN, GateStatus.UNSUPPORTED_CONFIG)
    return ReplayResult(
        n=n,
        fail=fail,
        warn_or_fail=warn_or_fail,
        fail_ci=wilson_interval(fail, n),
        warn_or_fail_ci=wilson_interval(warn_or_fail, n),
    )
