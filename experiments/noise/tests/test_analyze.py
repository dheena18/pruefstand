"""T6.3 S2 (core): sigma_d is cluster-aware and pooled over pairs; the MDE table and the quota."""

import math

import numpy as np
import polars as pl
import pytest
from noise.analyze import MAX_MDE_FACTOR, clusters_needed, mde, mde_table, sigma_table

from pruefstand.core.config.gate import GatePolicy, MetricPolicy
from pruefstand.gate.stats import minimum_detectable_effect

POLICY = GatePolicy(
    metrics={
        "context_recall": MetricPolicy(max_drop=0.05),
        "faithfulness": MetricPolicy(max_drop=0.05),
    }
)


def diffs(
    sigma: float, *, clusters: int = 400, pairs: int = 2, arm: str = "churn", seed: int = 3
) -> pl.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for pair in range(pairs):
        means = rng.normal(0.0, sigma, size=clusters)
        for c, m in enumerate(means):
            for offset in (-0.01, 0.01):  # two cases per cluster around the cluster mean
                rows.append(
                    {"arm": arm, "kind": "temp03", "pair": f"p{pair}", "metric": "context_recall",
                     "slice": "overall", "cluster_id": f"k{c}", "diff": float(m + offset)}
                )  # fmt: skip
    return pl.DataFrame(rows)


def test_sigma_is_the_spread_of_cluster_means_pooled_over_pairs() -> None:
    table = sigma_table(diffs(0.1))
    kind = table.filter(pl.col("kind") == "temp03").row(0, named=True)
    pooled = table.filter(pl.col("kind") == "all").row(0, named=True)
    assert kind["sigma_d"] == pytest.approx(
        0.1, rel=0.08
    )  # case offsets cancel in the cluster mean
    assert (kind["pairs"], kind["clusters"]) == (2, 400)
    assert pooled["sigma_d"] == pytest.approx(kind["sigma_d"])


def test_pooling_is_the_root_mean_of_the_variances() -> None:
    both = pl.concat(
        [
            diffs(0.1, pairs=1, seed=1),
            diffs(0.2, pairs=1, seed=2).with_columns(pl.lit("p9").alias("pair")),
        ]
    )
    table = sigma_table(both)
    pooled = table.filter(pl.col("kind") == "all")["sigma_d"][0]
    per_pair = [diffs(0.1, pairs=1, seed=1), diffs(0.2, pairs=1, seed=2)]
    variances = [
        sigma_table(t).filter(pl.col("kind") == "all")["sigma_d"][0] ** 2 for t in per_pair
    ]
    assert pooled == pytest.approx(math.sqrt(sum(variances) / 2))


def test_mde_rows_use_the_family_size_and_flag_too_few_clusters() -> None:
    sigma = sigma_table(diffs(0.1))
    table = mde_table(sigma, {("context_recall", "overall"): 220}, POLICY, m_family=12)
    row = table.row(0, named=True)
    se = row["sigma_d"] / math.sqrt(220)
    assert row["mde"] == pytest.approx(minimum_detectable_effect(se, 0.025, 0.05, m=12))
    assert row["gated"]
    assert row["ok"]
    assert row["clusters_needed"] is None
    small = mde_table(sigma, {("context_recall", "overall"): 20}, POLICY, m_family=12).row(
        0, named=True
    )
    assert not small["gated"]


def test_a_failing_row_gets_the_cluster_quota_that_would_pass() -> None:
    sigma = sigma_table(diffs(0.6))
    row = mde_table(sigma, {("context_recall", "overall"): 220}, POLICY, m_family=12).row(
        0, named=True
    )
    assert not row["ok"]
    needed = row["clusters_needed"]
    target = MAX_MDE_FACTOR * 0.05
    assert (
        mde(row["sigma_d"], needed, POLICY, 0.05, 12)
        <= target
        < mde(row["sigma_d"], needed - 1, POLICY, 0.05, 12)
    )
    assert clusters_needed(row["sigma_d"], POLICY, 0.05, 12) == needed
