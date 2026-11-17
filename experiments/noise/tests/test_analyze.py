"""T6.3 S2 (core): size-weighted sigma_d, pooling, the MDE table and the quota (D1275)."""

import math

import numpy as np
import polars as pl
import pytest
from noise.analyze import MAX_MDE_FACTOR, clusters_needed, mde, mde_table, sigma_table

from pruefstand.core.config.gate import GatePolicy, MetricPolicy
from pruefstand.core.errors import ConfigError
from pruefstand.gate.stats import minimum_detectable_effect, paired_cluster_bootstrap

POLICY = GatePolicy(
    metrics={
        "context_recall": MetricPolicy(max_drop=0.05),
        "faithfulness": MetricPolicy(max_drop=0.05),
    }
)


def frame(cases: list[tuple[str, float]], *, pair: str = "p0", arm: str = "churn") -> pl.DataFrame:
    """Rows of one pair: (cluster id, case diff)."""
    return pl.DataFrame(
        [
            {"arm": arm, "kind": "temp03", "pair": pair, "metric": "context_recall",
             "slice": "overall", "cluster_id": c, "diff": d}
            for c, d in cases
        ]
    )  # fmt: skip


def normal_clusters(
    sigma: float, k: int, seed: int, sizes: tuple[int, ...] = (1,)
) -> list[tuple[str, float]]:
    rng = np.random.default_rng(seed)
    out = []
    for c, mean in enumerate(rng.normal(0.0, sigma, size=k)):
        out += [(f"k{c}", float(mean))] * sizes[c % len(sizes)]
    return out


def kind_sigma(table: pl.DataFrame) -> float:
    return float(table.filter(pl.col("kind") == "temp03")["sigma_d"][0])


def test_prompt_plan_sigma_recovered_within_ten_percent() -> None:
    table = sigma_table(frame(normal_clusters(0.2, 300, seed=1234)))
    assert kind_sigma(table) == pytest.approx(0.2, rel=0.10)


def test_exact_value_uses_cluster_means_and_k_minus_one() -> None:
    # cluster means 0, 0.3, 0.6 from very different cases: sigma^2 = (0.09 + 0 + 0.09) / 2
    cases = [("a", -0.1), ("a", 0.1), ("b", 0.0), ("b", 0.6), ("c", 0.5), ("c", 0.7)]
    assert kind_sigma(sigma_table(frame(cases))) == pytest.approx(0.3)


def test_se_matches_the_gate_bootstrap_with_unequal_cluster_sizes() -> None:
    cases = normal_clusters(0.2, 300, seed=7, sizes=(1, 9))
    sigma = kind_sigma(sigma_table(frame(cases)))
    diffs = np.array([d for _, d in cases])
    ids = np.array([c for c, _ in cases])
    boot = paired_cluster_bootstrap(
        diffs, ids, n_resamples=4000, confidence=0.95, rng=np.random.default_rng(1)
    )
    assert sigma / math.sqrt(300) == pytest.approx(boot.se, rel=0.10)


def test_pooling_is_the_root_mean_of_the_variances() -> None:
    first = frame(normal_clusters(0.1, 200, seed=1), pair="p1")
    second = frame(normal_clusters(0.2, 200, seed=2), pair="p2")
    pooled = sigma_table(pl.concat([first, second])).filter(pl.col("kind") == "all")["sigma_d"][0]
    variances = [kind_sigma(sigma_table(f)) ** 2 for f in (first, second)]
    assert pooled == pytest.approx(math.sqrt(sum(variances) / 2))


def test_a_pair_with_one_cluster_is_refused() -> None:
    with pytest.raises(ConfigError, match="fewer than 2 clusters"):
        sigma_table(frame([("only", 0.1), ("only", 0.2)]))


def _row(sigma: float, k: int) -> dict[str, float]:
    table = sigma_table(frame(normal_clusters(sigma, 400, seed=3)))
    rows = mde_table(table, {("context_recall", "overall"): k}, POLICY, m_family=12)
    row: dict[str, float] = rows.row(0, named=True)
    return row


def test_mde_uses_the_holm_family_when_significance_binds() -> None:
    row = _row(0.6, 220)
    se = float(row["sigma_d"]) / math.sqrt(220)
    assert row["mde"] == pytest.approx(minimum_detectable_effect(se, 0.025, 0.05, m=12))
    assert row["mde"] > minimum_detectable_effect(se, 0.025, 0.05, m=1) + 0.01


def test_mde_never_drops_below_the_delta_floor() -> None:
    row = _row(0.05, 220)
    se = float(row["sigma_d"]) / math.sqrt(220)
    assert row["mde"] >= 0.05 + 0.8416 * se - 1e-9
    assert row["ok"]
    assert row["clusters_needed"] is None


@pytest.mark.parametrize(("k", "gated"), [(30, True), (29, False)])
def test_gated_from_exactly_min_clusters(k: int, gated: bool) -> None:  # noqa: FBT001
    assert _row(0.1, k)["gated"] is gated


def test_a_failing_row_gets_the_cluster_quota_that_would_pass() -> None:
    row = _row(0.6, 220)
    assert not row["ok"]
    needed = int(str(row["clusters_needed"]))
    sigma = float(row["sigma_d"])
    target = MAX_MDE_FACTOR * 0.05
    assert mde(sigma, needed, POLICY, 0.05, 12) <= target
    assert mde(sigma, needed - 1, POLICY, 0.05, 12) > target
    assert clusters_needed(sigma, POLICY, 0.05, 12) == needed
