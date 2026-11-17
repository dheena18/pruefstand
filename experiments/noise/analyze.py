"""T6.3 S2 (core): sigma_d per metric x gated slice from paired diffs, MDE table (SPEC §7.2, §7.3).

Input: one row per paired case diff (candidate - baseline) with ``arm`` (``noop``, ``churn``,
``repeat``), ``kind`` (e.g. ``reindex``, ``prompt_synonym``), ``pair`` (one run pair),
``metric``, ``slice``, ``cluster_id``, ``diff``. Cluster-aware: the case diffs of a cluster are
averaged first; sigma_d of a pair is the standard deviation of its cluster means, and sigma_d of
a kind or an arm is pooled over its pairs as the root mean of the variances. ``se = sigma_d /
sqrt(clusters)`` is the standard error the gate's bootstrap sees at that cluster count. The MDE
uses ``minimum_detectable_effect(se, alpha, delta, m=m_family)``; the check is MDE <= 1.5 δ with
sigma_d(churn), and a failing row gets the cluster count that would pass (never a changed δ).
"""

import math
from collections.abc import Mapping

import polars as pl

from pruefstand.core.config.gate import GatePolicy
from pruefstand.gate.stats import minimum_detectable_effect

KEYS = ["arm", "kind", "metric", "slice"]
MAX_MDE_FACTOR = 1.5


def sigma_table(diffs: pl.DataFrame) -> pl.DataFrame:
    """sigma_d per (arm, kind, metric, slice), plus a pooled ``kind == "all"`` row per arm.

    Returns:
        ``arm, kind, metric, slice, sigma_d, pairs, clusters`` (``clusters``: the mean cluster
        count per pair), sorted.
    """
    per_pair = (
        diffs.group_by([*KEYS, "pair", "cluster_id"])
        .agg(pl.col("diff").mean())
        .group_by([*KEYS, "pair"])
        .agg(pl.col("diff").var(ddof=1).alias("var"), pl.len().alias("clusters"))
    )
    by_kind = per_pair.group_by(KEYS).agg(
        pl.col("var").mean().sqrt().alias("sigma_d"),
        pl.len().alias("pairs"),
        pl.col("clusters").mean().alias("clusters"),
    )
    pooled = (
        per_pair.with_columns(pl.lit("all").alias("kind"))
        .group_by(KEYS)
        .agg(
            pl.col("var").mean().sqrt().alias("sigma_d"),
            pl.len().alias("pairs"),
            pl.col("clusters").mean().alias("clusters"),
        )
    )
    return pl.concat([by_kind, pooled]).sort(KEYS)


def mde(sigma_d: float, clusters: int, policy: GatePolicy, delta: float, m_family: int) -> float:
    """Minimum detectable drop at ``clusters`` applicable clusters (power 0.8)."""
    se = sigma_d / math.sqrt(clusters)
    return minimum_detectable_effect(se, policy.alpha, delta, m=m_family)


def clusters_needed(sigma_d: float, policy: GatePolicy, delta: float, m_family: int) -> int:
    """Smallest cluster count with MDE <= 1.5 δ (power 0.8).

    Examples:
        >>> from pruefstand.core.config.gate import GatePolicy, MetricPolicy
        >>> p = GatePolicy(metrics={"context_recall": MetricPolicy(max_drop=0.05)})
        >>> k = clusters_needed(0.3, p, 0.05, 10)
        >>> mde(0.3, k, p, 0.05, 10) <= 0.075 < mde(0.3, k - 1, p, 0.05, 10)
        True
    """
    target = MAX_MDE_FACTOR * delta
    low, high = 1, 2
    while mde(sigma_d, high, policy, delta, m_family) > target:
        low, high = high, high * 2
    while low + 1 < high:
        mid = (low + high) // 2
        if mde(sigma_d, mid, policy, delta, m_family) > target:
            low = mid
        else:
            high = mid
    return high


def mde_table(
    sigma: pl.DataFrame,
    applicable: Mapping[tuple[str, str], int],
    policy: GatePolicy,
    *,
    arm: str = "churn",
    m_family: int,
) -> pl.DataFrame:
    """One row per gated (metric, slice): pooled sigma_d, clusters, MDE, MDE <= 1.5 δ, quota.

    Args:
        sigma: output of :func:`sigma_table`.
        applicable: (metric, slice) -> applicable cluster count at the split's real size.
        policy: the shipped gate policy (δ, alpha, min_clusters).
        arm: the sigma_d arm used for sizing (``churn``, SPEC §7.3).
        m_family: size of the run's one Holm family (gated metric x gated slice pairs).

    Returns:
        ``metric, slice, sigma_d, clusters, gated, delta, mde, ok, clusters_needed`` (``gated`` is
        false below ``min_clusters``; ``clusters_needed`` is null when ``ok``).
    """
    pooled = sigma.filter((pl.col("arm") == arm) & (pl.col("kind") == "all"))
    rows = []
    for row in pooled.iter_rows(named=True):
        rule = policy.metrics.get(row["metric"])
        key = (row["metric"], row["slice"])
        if rule is None or rule.max_drop is None or key not in applicable:
            continue
        k, delta = applicable[key], rule.max_drop
        value = mde(row["sigma_d"], k, policy, delta, m_family)
        ok = value <= MAX_MDE_FACTOR * delta
        rows.append(
            {
                "metric": row["metric"], "slice": row["slice"], "sigma_d": row["sigma_d"],
                "clusters": k, "gated": k >= policy.min_clusters, "delta": delta, "mde": value,
                "ok": ok,
                "clusters_needed": (
                    None if ok else clusters_needed(row["sigma_d"], policy, delta, m_family)
                ),
            }
        )  # fmt: skip
    return pl.DataFrame(rows).sort(["metric", "slice"])
