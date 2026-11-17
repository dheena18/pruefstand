"""T7.3 S3: drops per config x perturbation, cluster bootstrap CI, BH fix-first list."""

from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import pytest
from rq1.analyze import CLOSED_BOOK, drop_table, fix_first, paired_diffs, write_heatmap

PERTURBATIONS = ("typos", "umlaut_translit", "compound_split")


def results(
    effect: dict[tuple[str, str, str], float],
    *,
    configs: tuple[str, ...] = ("c1",),
    metrics: tuple[str, ...] = ("context_recall",),
    clusters: int = 40,
    base: float = 0.8,
    noise: float = 0.0,
    seed: int = 7,
) -> pl.DataFrame:
    """One base and one variant per perturbation per cluster; variant = base + effect (+ noise)."""
    rng = np.random.default_rng(seed)
    rows: list[dict[str, Any]] = []
    for config in configs:
        for metric in metrics:
            for k in range(clusters):
                base_id = f"b{k}"
                row = {
                    "config": config,
                    "base_id": base_id,
                    "cluster_id": f"k{k}",
                    "metric": metric,
                }
                rows.append({**row, "case_id": base_id, "perturbation": None, "value": base})
                for pert in PERTURBATIONS:
                    shift = effect.get((config, pert, metric), 0.0) + noise * rng.normal()
                    value = min(max(base + shift, 0.0), 1.0)
                    rows.append(
                        {
                            **row,
                            "case_id": f"{base_id}-{pert}",
                            "perturbation": pert,
                            "value": value,
                        }
                    )
    frame = pl.DataFrame(rows)
    return frame.with_columns(
        pl.lit("ok").alias("status"), pl.lit([], dtype=pl.List(pl.Utf8)).alias("tags")
    )


def table(frame: pl.DataFrame, **kwargs: Any) -> pl.DataFrame:
    return drop_table(paired_diffs(frame), n_resamples=999, seed=1234, **kwargs)


def cell(t: pl.DataFrame, config: str, pert: str, metric: str) -> dict[str, Any]:
    rows = t.filter(
        (pl.col("config") == config)
        & (pl.col("perturbation") == pert)
        & (pl.col("metric") == metric)
    )
    assert rows.height == 1
    return rows.row(0, named=True)


def test_a_typo_only_drop_is_found_and_its_ci_excludes_zero() -> None:
    t = table(results({("c1", "typos", "context_recall"): -0.2}))
    typos = cell(t, "c1", "typos", "context_recall")
    assert typos["drop"] == pytest.approx(-0.2)
    assert typos["ci_high"] < 0
    for pert in ("umlaut_translit", "compound_split"):
        assert cell(t, "c1", pert, "context_recall")["drop"] == pytest.approx(0.0)


def test_cases_of_one_cluster_resample_together() -> None:
    frame = results({("c1", "typos", "context_recall"): -0.2}, clusters=30)
    twin = frame.filter(pl.col("cluster_id") == "k0").with_columns(
        (pl.col("base_id") + "x").alias("base_id"), (pl.col("case_id") + "x").alias("case_id")
    )
    typos = cell(table(pl.concat([frame, twin])), "c1", "typos", "context_recall")
    assert typos["n_clusters"] == 30  # two bases in k0 are one resampling unit
    assert typos["n_cases"] == 31


def test_rows_that_are_not_ok_are_ignored() -> None:
    frame = results({("c1", "typos", "context_recall"): -0.2})
    broken = frame.with_columns(
        pl.when((pl.col("perturbation") == "typos") & (pl.col("cluster_id") == "k0"))
        .then(pl.lit("error"))
        .otherwise(pl.col("status"))
        .alias("status")
    )
    assert cell(table(broken), "c1", "typos", "context_recall")["n_cases"] == 39


def test_closed_book_cases_are_left_out_of_the_second_table() -> None:
    frame = results({("c1", "typos", "answer_correctness"): -0.2}, metrics=("answer_correctness",))
    tagged = frame.with_columns(
        pl.when(pl.col("cluster_id").is_in([f"k{i}" for i in range(10)]))
        .then(pl.lit([CLOSED_BOOK]))
        .otherwise(pl.col("tags"))
        .alias("tags")
    )
    every = cell(table(tagged), "c1", "typos", "answer_correctness")
    sensitive = cell(table(tagged, exclude_closed_book=True), "c1", "typos", "answer_correctness")
    assert every["n_clusters"] == 40
    assert sensitive["n_clusters"] == 30


def test_chunking_drop_shows_on_evidence_recall_not_context_recall() -> None:
    # A fixed-chunk config keeps the doc-level hit (context_recall 1.0) but loses the span half
    # the time.
    frame = results(
        {("fixed512", "typos", "evidence_recall"): -0.5},
        configs=("fixed512",),
        metrics=("context_recall", "evidence_recall"),
        base=1.0,
    )
    t = table(frame)
    assert cell(t, "fixed512", "typos", "context_recall")["drop"] == pytest.approx(0.0)
    assert cell(t, "fixed512", "typos", "evidence_recall")["drop"] == pytest.approx(-0.5)


def test_only_the_real_effect_survives_bh_in_the_fix_first_list() -> None:
    configs = tuple(f"c{i}" for i in range(14))  # 14 configs x 3 perturbations = 42 cells
    frame = results({("c3", "typos", "context_recall"): -0.2}, configs=configs, noise=0.05, seed=11)
    first = fix_first(table(frame), q=0.10, top=5)
    assert [(r["config"], r["perturbation"]) for r in first.iter_rows(named=True)] == [
        ("c3", "typos")
    ]
    assert first["p_bh"][0] < 0.10


def test_the_heatmap_is_written(tmp_path: Path) -> None:
    t = table(results({("c1", "typos", "context_recall"): -0.2}, configs=("c1", "c2")))
    out = write_heatmap(t, "context_recall", tmp_path / "heatmap_recall.png")
    assert out.is_file()
    assert out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_the_table_is_identical_for_the_same_seed() -> None:
    frame = results({("c1", "typos", "context_recall"): -0.2}, noise=0.05)
    assert table(frame).equals(table(frame))


def test_a_significant_improvement_is_never_on_the_fix_first_list() -> None:
    # The bootstrap p is one-sided ("no drop"), so an improvement normally has a large p; fix_first
    # still keeps only drops, also for a table whose p-values come from elsewhere.
    t = pl.DataFrame(
        {
            "config": ["c1", "c2", "c3"],
            "perturbation": ["typos", "typos", "typos"],
            "metric": ["context_recall"] * 3,
            "drop": [-0.2, 0.25, -0.01],
            "ci_low": [-0.3, 0.15, -0.05],
            "ci_high": [-0.1, 0.35, 0.03],
            "p": [0.001, 0.001, 0.6],
            "n_cases": [40, 40, 40],
            "n_clusters": [40, 40, 40],
        }
    )
    first = fix_first(t, q=0.10, top=5)
    assert first["config"].to_list() == ["c1"]
