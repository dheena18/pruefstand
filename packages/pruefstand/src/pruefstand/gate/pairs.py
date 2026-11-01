"""Paired (metric, slice) comparisons of the gate (T1.7 steps 5 and 6).

``metric_pairs`` lists the pairs of one metric in the contractual order (``overall``,
``perturbed_all``, then the dimensions of ``GatePolicy.slices`` in order, values sorted);
``bootstrap_pairs`` runs the paired cluster bootstrap on all pairs of the run in that order with
one ``rng`` (the order is part of the contract); ``build_decisions`` applies Holm (one family: all
testable gated pairs of the run) and Benjamini-Hochberg (all testable informational pairs).

**Adaptive re-run (SPEC §7.2, ADR-0007).** After the first pass, a testable gated pair whose
observed drop is relevant (``mean_diff < -max_drop``) and whose bootstrap p lies within
``3 * sqrt(p (1 - p) / B)`` of a Holm threshold (``alpha / j`` or ``warn_p / j``, ``j`` = 1..m) is
bootstrapped again with ``B = 200 000`` from the same ``rng``, in pair order. Sign-test p-values
are exact and never re-run.
"""

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from pruefstand.core.config import GatePolicy
from pruefstand.core.enums import GateStatus
from pruefstand.core.models.gate import BootstrapResult, SliceDecision
from pruefstand.gate.correction import bh_adjust, holm_adjust
from pruefstand.gate.decision import decide
from pruefstand.gate.stats import minimum_detectable_effect, paired_cluster_bootstrap
from pruefstand.gate.tables import OVERALL, PERTURBED_ALL, PairedTable, slice_members, slice_values

RERUN_RESAMPLES = 200_000
MC_SIGMAS = 3.0
MIN_APPLICABLE_CLUSTERS = 30  # D117: fewer applicable clusters on `overall` -> informational
RETRIEVAL_METRICS = ("context_recall", "ndcg_at_k")
BH_NOTABLE_Q = 0.10
POWER = 0.8
APPLICABLE_REASON = "applicable_clusters<30"


@dataclass
class Pair:
    """One (metric, slice) comparison; ``result`` is filled by ``bootstrap_pairs``."""

    metric: str
    dimension: str
    value: str
    gated: bool
    reason: str | None
    max_drop: float
    table: PairedTable
    mask: NDArray[np.bool_]
    result: BootstrapResult | None = None


def informational_reason(
    table: PairedTable, metric: str, informational: Mapping[str, str]
) -> str | None:
    """Return why ``metric`` is informational here, or ``None`` (the pipeline's reason wins)."""
    if metric in informational:
        return informational[metric]
    members = slice_members(table, OVERALL, OVERALL)
    if np.unique(table.cluster_ids[members]).size < MIN_APPLICABLE_CLUSTERS:
        return APPLICABLE_REASON
    return None


def metric_pairs(
    table: PairedTable, policy: GatePolicy, max_drop: float, reason: str | None
) -> list[Pair]:
    """Return the pairs of one metric in the contractual order (step 6)."""
    metric = table.metric
    gated_metric = reason is None
    specs: list[tuple[str, str]] = [(OVERALL, OVERALL)]
    if metric in RETRIEVAL_METRICS and slice_members(table, PERTURBED_ALL, PERTURBED_ALL).any():
        specs.append((PERTURBED_ALL, PERTURBED_ALL))
    for dimension in policy.slices:
        specs.extend((dimension, value) for value in slice_values(table, dimension))
    return [
        Pair(
            metric=metric,
            dimension=dimension,
            value=value,
            gated=gated_metric and dimension in policy.gated_slices,
            reason=reason,
            max_drop=max_drop,
            table=table,
            mask=slice_members(table, dimension, value),
        )
        for dimension, value in specs
    ]


def _bootstrap(
    pair: Pair, policy: GatePolicy, n_resamples: int, rng: np.random.Generator
) -> BootstrapResult:
    return paired_cluster_bootstrap(
        pair.table.diffs[pair.mask],
        pair.table.cluster_ids[pair.mask],
        n_resamples=n_resamples,
        confidence=policy.metrics[pair.metric].confidence,
        rng=rng,
        alpha=policy.alpha,
    )


def _testable(pair: Pair, policy: GatePolicy) -> bool:
    return pair.result is not None and pair.result.n_clusters >= policy.min_clusters


def _family_size(pairs: list[Pair], policy: GatePolicy) -> int:
    return sum(1 for p in pairs if p.gated and _testable(p, policy))


def holm_thresholds(m: int, alpha: float, warn_p: float) -> NDArray[np.float64]:
    """Return the p-value thresholds ``alpha / j`` and ``warn_p / j`` for ``j = 1..m``."""
    steps = np.arange(1, max(m, 1) + 1, dtype=np.float64)
    return np.concatenate([alpha / steps, warn_p / steps])


def near_threshold(p_value: float, n_resamples: int, thresholds: NDArray[np.float64]) -> bool:
    """Tell whether a bootstrap p lies within 3 Monte-Carlo standard errors of a threshold.

    The standard error of a bootstrap p-value ``p`` from B resamples is ``sqrt(p (1 - p) / B)``.

    Examples:
        The 8-pair family of the gate (R2): p = 1/2001 at B = 2000 is 0.0026 away from the first
        Holm step 0.025 / 8 = 0.0031, more than 3 SE (0.0015), so the p-value stands. With 13
        pairs the step is 0.0019, 0.0014 away, inside 3 SE: the pair is re-run.

        >>> near_threshold(1 / 2001, 2000, holm_thresholds(8, 0.025, 0.10))
        False
        >>> near_threshold(1 / 2001, 2000, holm_thresholds(13, 0.025, 0.10))
        True
    """
    se = float(np.sqrt(p_value * (1.0 - p_value) / n_resamples))
    return bool(np.any(np.abs(thresholds - p_value) <= MC_SIGMAS * se))


def _refine(pairs: list[Pair], policy: GatePolicy, rng: np.random.Generator) -> None:
    m = _family_size(pairs, policy) if policy.correction == "holm" else 1
    thresholds = holm_thresholds(m, policy.alpha, policy.warn_p)
    for pair in pairs:
        result = pair.result
        if not (pair.gated and _testable(pair, policy)) or result is None:
            continue
        relevant = result.method == "bootstrap" and result.mean_diff < -pair.max_drop
        if relevant and near_threshold(result.p_value, result.n_resamples, thresholds):
            pair.result = _bootstrap(pair, policy, RERUN_RESAMPLES, rng)


def bootstrap_pairs(pairs: list[Pair], policy: GatePolicy, rng: np.random.Generator) -> None:
    """Bootstrap each pair in list order (0 paired cases: no draws), then re-run near thresholds."""
    for pair in pairs:
        if pair.mask.any():
            pair.result = _bootstrap(pair, policy, policy.n_resamples, rng)
    _refine(pairs, policy, rng)


def _means(pair: Pair) -> tuple[float, float]:
    if not pair.mask.any():
        return 0.0, 0.0
    return float(pair.table.base_values[pair.mask].mean()), float(
        pair.table.cand_values[pair.mask].mean()
    )


def _decision(
    pair: Pair,
    status: GateStatus,
    *,
    p_adjusted: float | None = None,
    mde: float | None = None,
    notable: bool = False,
) -> SliceDecision:
    base_mean, cand_mean = _means(pair)
    return SliceDecision(
        metric=pair.metric,
        dimension=pair.dimension,
        value=pair.value,
        status=status,
        gated=pair.gated,
        notable=notable,
        baseline_mean=base_mean,
        candidate_mean=cand_mean,
        result=pair.result,
        p_adjusted=p_adjusted,
        mde=mde,
        max_drop=pair.max_drop,
        n_clusters=pair.result.n_clusters if pair.result else 0,
        informational_reason=pair.reason,
    )


def build_decisions(pairs: list[Pair], policy: GatePolicy) -> list[SliceDecision]:
    """Return one ``SliceDecision`` per pair, in pair order (steps 6, 11).

    Gated testable pairs: one Holm family over all of them (``correction="none"``: raw p), status
    by ``decide``, MDE for family size m. Informational testable pairs: BH adjusted p, status
    ``PASS``, ``notable = bh < 0.10 and mean_diff < -max_drop``. Untestable pairs (fewer than
    ``min_clusters``, or no paired case): ``INSUFFICIENT_DATA``.
    """
    gated = [p for p in pairs if p.gated and _testable(p, policy)]
    info = [p for p in pairs if not p.gated and _testable(p, policy)]
    raw = [p.result.p_value for p in gated if p.result]
    holm = holm_adjust(raw) if policy.correction == "holm" else raw
    m = len(gated) if policy.correction == "holm" else 1
    adjusted = {id(p): holm[i] for i, p in enumerate(gated)}
    adjusted |= {
        id(p): q
        for p, q in zip(info, bh_adjust([p.result.p_value for p in info if p.result]), strict=True)
    }
    out: list[SliceDecision] = []
    for pair in pairs:
        result = pair.result
        if result is None or id(pair) not in adjusted:
            out.append(_decision(pair, GateStatus.INSUFFICIENT_DATA))
            continue
        p_adj = adjusted[id(pair)]
        status = decide(
            result, max_drop=pair.max_drop, p_adjusted=p_adj, alpha=policy.alpha,
            warn_p=policy.warn_p, min_clusters=policy.min_clusters, gated=pair.gated,
        )  # fmt: skip
        if pair.gated:
            mde = minimum_detectable_effect(result.se, policy.alpha, pair.max_drop, POWER, m)
            out.append(_decision(pair, status, p_adjusted=p_adj, mde=mde))
        else:
            notable = p_adj < BH_NOTABLE_Q and result.mean_diff < -pair.max_drop
            out.append(_decision(pair, status, p_adjusted=p_adj, notable=notable))
    return out
