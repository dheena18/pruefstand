"""T6.3 S5 (offline): paired diffs with the gate's pairing, mde.csv rows and the output writers."""

from pathlib import Path

import numpy as np
import polars as pl
import pytest
from noise import outputs
from noise.outputs import (
    MDE_COLUMNS,
    mde_rows,
    paired_diffs,
    replay_rows,
    slice_label,
    timing_row,
    write_mde,
    write_paired_diffs,
    write_rows,
    write_sigma,
)
from noise.replay import ReplayResult
from testsupport.builders import fixture_f0, make_case, make_run
from testsupport.gate_helpers import DIRECTIONS, POLICY

from pruefstand.core.config.gate import GatePolicy, MetricPolicy
from pruefstand.core.errors import ConfigError

KEYS = {"arm": "noop", "kind": "reindex", "pair": "p0", "split": "core"}


def test_paired_diffs_use_the_gate_slices_and_orientation() -> None:
    cases, values = fixture_f0()
    base = make_run("b", cases, values)
    drop: dict[str, list[float | None]] = {**values, "context_recall": [0.6] * len(cases)}
    diffs = paired_diffs(base, make_run("c", cases, drop), POLICY, directions=DIRECTIONS, **KEYS)
    cr = diffs.filter(pl.col("metric") == "context_recall")
    assert set(cr["slice"]) >= {"overall", "lang=de", "lang=en", "tenant=kanzlei_mueller"}
    assert cr.filter(pl.col("slice") == "overall")["diff"].to_list() == pytest.approx([-0.2] * 120)
    assert cr.filter(pl.col("slice") == "overall")["cluster_id"].n_unique() == 60
    assert set(diffs["metric"]) <= {m for m, r in POLICY.metrics.items() if r.max_drop is not None}
    assert {c: diffs[c][0] for c in KEYS} == KEYS


def test_perturbed_cases_count_only_in_perturbed_all() -> None:
    cases, values = fixture_f0()
    perturbed = [make_case(200 + i, cluster=i, perturbation="typo", base=2 * i) for i in range(40)]
    every = cases + perturbed
    vals = {m: v + [v[0]] * 40 for m, v in values.items()}
    diffs = paired_diffs(
        make_run("b", every, vals),
        make_run("c", every, vals),
        POLICY,
        directions=DIRECTIONS,
        **KEYS,
    )
    cr = diffs.filter(pl.col("metric") == "context_recall")
    assert cr.filter(pl.col("slice") == "overall").height == 120
    assert cr.filter(pl.col("slice") == "perturbed_all").height == 40


def synthetic(arm: str, sigma_d: float, clusters: int, rng: np.random.Generator) -> pl.DataFrame:
    frames = []
    for pair in range(5):
        shift = rng.normal(0.0, sigma_d, clusters)
        frames.append(pl.DataFrame({
            "arm": arm, "kind": "k", "pair": f"{arm}{pair}", "split": "core",
            "metric": "context_recall", "slice": "overall",
            "cluster_id": [f"k{c:03d}" for c in range(clusters)], "diff": shift,
        }))  # fmt: skip
    return pl.concat(frames)


def test_mde_rows_size_with_churn_replay_with_noop_and_report_the_floor() -> None:
    rng = np.random.default_rng(1234)
    diffs = pl.concat([synthetic(a, s, 300, rng) for a, s in
                       [("noop", 0.30), ("churn", 0.35), ("repeat", 0.05)]])  # fmt: skip
    small = synthetic("churn", 0.35, 25, rng).with_columns(pl.lit("lang=en").alias("slice"))
    policy = GatePolicy(metrics={"context_recall": MetricPolicy(max_drop=0.05)})
    rows = {r["slice"]: r for r in mde_rows(pl.concat([diffs, small]), policy, "core")}
    main = rows["overall"]
    assert main["sigma_d_churn"] == pytest.approx(0.35, rel=0.1)
    assert main["sigma_d_noop"] == pytest.approx(0.30, rel=0.1)
    assert main["sigma_d_repeat"] == pytest.approx(0.05, rel=0.1)
    assert main["m_family"] == 1
    assert main["gated"] is True
    assert main["detectable_drop"] > main["detectable_drop_noop"]  # type: ignore[operator]  # floats
    assert rows["lang=en"]["gated"] is False  # 25 applicable clusters (W3.6)
    assert rows["lang=en"]["sigma_d_noop"] is None


def test_write_mde_keeps_the_columns_and_refuses_duplicates(tmp_path: Path) -> None:
    row = dict.fromkeys(MDE_COLUMNS, 0.0) | {"metric": "m", "slice": "overall", "split": "core"}
    write_mde(tmp_path / "mde.csv", [row, row | {"split": "full_b0"}])
    assert pl.read_csv(tmp_path / "mde.csv").columns == MDE_COLUMNS
    with pytest.raises(ConfigError, match="more than one row"):
        write_mde(tmp_path / "mde.csv", [row, row])


def test_sigma_replay_timings_and_parquet(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rng = np.random.default_rng(1)
    diffs = pl.concat([synthetic("noop", 0.3, 40, rng), synthetic("churn", 0.3, 40, rng)])
    write_sigma(tmp_path / "sigma.csv", diffs)
    assert {"split", "arm", "kind", "sigma_d"} <= set(pl.read_csv(tmp_path / "sigma.csv").columns)
    result = ReplayResult(n=2000, fail=10, warn_or_fail=50, fail_ci=(0.002, 0.009),
                          warn_or_fail_ci=(0.019, 0.033))  # fmt: skip
    write_rows(tmp_path / "replay.csv", [replay_rows("noop", result), replay_rows("churn", result)])
    replay = pl.read_csv(tmp_path / "replay.csv")
    assert replay["arm"].to_list() == ["noop", "churn"]
    assert replay["fail_rate"][0] == 0.005
    assert timing_row("reranker_lane", 1300.0, 1200.0)["within_budget"] is False
    assert timing_row("first_load", 90.0, None)["within_budget"] is None
    assert write_paired_diffs(tmp_path / "pd.parquet", diffs) < 1_000_000
    monkeypatch.setattr(outputs, "MAX_PARQUET_BYTES", 10)
    with pytest.raises(ConfigError, match="below 1 MB"):
        write_paired_diffs(tmp_path / "big.parquet", diffs)
    assert not (tmp_path / "big.parquet").exists()


def test_slice_labels() -> None:
    assert slice_label("perturbed_all", "perturbed_all") == "perturbed_all"
    assert slice_label("lang", "de") == "lang=de"
