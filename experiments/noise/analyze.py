"""T6.3 S2 (core): sigma_d per metric x gated slice from paired diffs, MDE table (SPEC §7.2, §7.3).

Input: one row per paired case diff (candidate - baseline) with ``arm`` (``noop``, ``churn``,
``repeat``), ``kind`` (e.g. ``reindex``), ``pair`` (one run pair), ``metric``, ``slice``,
``cluster_id``, ``diff``. The gate's bootstrap estimates the **case** mean and resamples clusters,
so a pair's sigma_d is the size-weighted spread of its cluster means::

    sigma_d^2 = sum_c (n_c / n_bar)^2 (dbar_c - dbar)^2 / (k - 1)

(``n_c`` cases in cluster c, ``n_bar`` the mean cluster size, ``dbar`` the case mean, ``k``
clusters), so that ``se = sigma_d / sqrt(k)`` is the standard error of the case mean under
cluster resampling. A kind or an arm (``kind == "all"``) pools its pairs as the root mean of the
variances. The MDE uses ``minimum_detectable_effect(se, alpha, delta, m=m_family)``; the check is
MDE <= 1.5 delta with sigma_d(churn), and a failing row gets the cluster count that would pass
(delta is never changed).
"""

import math
from collections.abc import Mapping

import polars as pl

from pruefstand.core.config.gate import GatePolicy
from pruefstand.core.errors import ConfigError
from pruefstand.gate.stats import minimum_detectable_effect

KEYS = ["arm", "kind", "metric", "slice"]
MAX_MDE_FACTOR = 1.5


def pair_variances(diffs: pl.DataFrame) -> pl.DataFrame:
    """Size-weighted variance of the cluster means per (arm, kind, metric, slice, pair).

    Raises:
        ConfigError: a pair has fewer than two clusters (no spread can be estimated).
    """
    clusters = diffs.group_by([*KEYS, "pair", "cluster_id"]).agg(
        pl.col("diff").mean().alias("mean"), pl.len().alias("n")
    )
    per_pair = clusters.group_by([*KEYS, "pair"]).agg(
        pl.len().alias("clusters"),
        ((pl.col("n") * pl.col("mean")).sum() / pl.col("n").sum()).alias("case_mean"),
        pl.col("n").mean().alias("n_bar"),
    )
    too_few = per_pair.filter(pl.col("clusters") < 2)
    if too_few.height:
        msg = f"pair {too_few['pair'][0]}: fewer than 2 clusters, sigma_d is undefined"
        raise ConfigError(msg)
    weighted = clusters.join(per_pair, on=[*KEYS, "pair"]).with_columns(
        ((pl.col("n") / pl.col("n_bar")) ** 2 * (pl.col("mean") - pl.col("case_mean")) ** 2).alias(
            "sq"
        )
    )
    return weighted.group_by([*KEYS, "pair"]).agg(
        (pl.col("sq").sum() / (pl.len() - 1)).alias("var"), pl.len().alias("clusters")
    )


def sigma_table(diffs: pl.DataFrame) -> pl.DataFrame:
    """sigma_d per (arm, kind, metric, slice), plus a pooled ``kind == "all"`` row per arm.

    Returns:
        ``arm, kind, metric, slice, sigma_d, pairs, clusters`` (``clusters``: the mean cluster
        count per pair), sorted.
    """
    per_pair = pair_variances(diffs)
    aggregate = [
        pl.col("var").mean().sqrt().alias("sigma_d"),
        pl.len().alias("pairs"),
        pl.col("clusters").mean().alias("clusters"),
    ]
    by_kind = per_pair.group_by(KEYS).agg(aggregate)
    pooled = per_pair.with_columns(pl.lit("all").alias("kind")).group_by(KEYS).agg(aggregate)
    return pl.concat([by_kind, pooled]).sort(KEYS)


def mde(sigma_d: float, clusters: int, policy: GatePolicy, delta: float, m_family: int) -> float:
    """Minimum detectable drop at ``clusters`` applicable clusters (power 0.8)."""
    se = sigma_d / math.sqrt(clusters)
    return minimum_detectable_effect(se, policy.alpha, delta, m=m_family)


def clusters_needed(sigma_d: float, policy: GatePolicy, delta: float, m_family: int) -> int:
    """Smallest cluster count with MDE <= 1.5 delta (power 0.8).

    Raises:
        ConfigError: delta is 0 (no finite cluster count reaches 0).

    Examples:
        >>> from pruefstand.core.config.gate import GatePolicy, MetricPolicy
        >>> p = GatePolicy(metrics={"context_recall": MetricPolicy(max_drop=0.05)})
        >>> k = clusters_needed(0.3, p, 0.05, 10)
        >>> mde(0.3, k, p, 0.05, 10) <= 0.075 < mde(0.3, k - 1, p, 0.05, 10)
        True
        >>> clusters_needed(0.0, p, 0.05, 10)
        1
    """
    if delta <= 0:
        msg = "delta must be positive for a cluster quota"
        raise ConfigError(msg)
    target = MAX_MDE_FACTOR * delta
    if mde(sigma_d, 1, policy, delta, m_family) <= target:
        return 1
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


def mde_row(
    key: tuple[str, str], sigma_d: float, k: int, policy: GatePolicy, *, m_family: int
) -> dict[str, object] | None:
    """The MDE row of one gated (metric, slice), or None for a metric without ``max_drop``."""
    metric, slice_ = key
    rule = policy.metrics.get(metric)
    if rule is None or rule.max_drop is None:
        return None
    delta = rule.max_drop
    value = mde(sigma_d, k, policy, delta, m_family)
    ok = value <= MAX_MDE_FACTOR * delta
    return {
        "metric": metric, "slice": slice_, "sigma_d": sigma_d, "clusters": k,
        "gated": k >= policy.min_clusters, "delta": delta, "mde": value, "ok": ok,
        "clusters_needed": None if ok else clusters_needed(sigma_d, policy, delta, m_family),
    }  # fmt: skip


def mde_table(
    sigma: pl.DataFrame,
    applicable: Mapping[tuple[str, str], int],
    policy: GatePolicy,
    *,
    arm: str = "churn",
    m_family: int,
) -> pl.DataFrame:
    """One row per (metric, slice) of ``applicable``: pooled sigma_d of ``arm``, MDE, check, quota.

    Args:
        sigma: output of :func:`sigma_table`.
        applicable: (metric, slice) -> applicable cluster count at the split's real size.
        policy: the shipped gate policy (delta, alpha, min_clusters).
        arm: the sigma_d arm used for sizing (``churn``, SPEC §7.3).
        m_family: size of the run's one Holm family (gated metric x gated slice pairs).

    Returns:
        ``metric, slice, sigma_d, clusters, gated, delta, mde, ok, clusters_needed`` (``gated``
        is false below ``min_clusters``; ``clusters_needed`` is null when ``ok``).
    """
    pooled = sigma.filter((pl.col("arm") == arm) & (pl.col("kind") == "all"))
    rows = []
    for row in pooled.iter_rows(named=True):
        key = (row["metric"], row["slice"])
        if key in applicable:
            built = mde_row(key, row["sigma_d"], applicable[key], policy, m_family=m_family)
            if built is not None:
                rows.append(built)
    return pl.DataFrame(rows).sort(["metric", "slice"])
