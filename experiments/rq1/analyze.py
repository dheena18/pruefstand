"""RQ1 analysis (T7.3 S3): drops per config x perturbation x metric, bootstrap CI, fix-first list.

Input: the rows of the grid runs (``results.parquet`` columns of interfaces §8 plus ``config``).
The drop of a perturbation is the mean over ``cluster_id`` of (metric(perturbed) - metric(base)):
case differences are averaged within each cluster first, then the cluster means go through the
gate's paired cluster bootstrap (``gate.stats.paired_cluster_bootstrap``, one-sided p for "no
drop"). The "fix first" list applies Benjamini-Hochberg at q = 0.10 over all config x
perturbation x metric cells before ranking (``bh_adjust``). Rows with ``status != "ok"`` are
ignored; ``exclude_closed_book`` drops the cases tagged ``closed_book_answerable`` (the
contamination control of the correctness table).
"""

from pathlib import Path

import matplotlib as mpl
import numpy as np
import polars as pl

from pruefstand.gate.correction import bh_adjust
from pruefstand.gate.stats import paired_cluster_bootstrap

mpl.use("Agg")
import matplotlib.pyplot as plt

CLOSED_BOOK = "closed_book_answerable"
KEYS = ["config", "perturbation", "metric"]
FIX_FIRST_Q = 0.10


def paired_diffs(results: pl.DataFrame) -> pl.DataFrame:
    """Pair every perturbed case with its base (same config, base and metric); one row per pair.

    Args:
        results: rows with ``config, case_id, base_id, cluster_id, perturbation, metric,
            value, status, tags``; ``perturbation`` is null for the base question.

    Returns:
        ``config, perturbation, metric, base_id, cluster_id, diff, closed_book``.
    """
    ok = results.filter(pl.col("status") == "ok").with_columns(
        pl.col("tags").list.contains(CLOSED_BOOK).alias("closed_book")
    )
    base = ok.filter(pl.col("perturbation").is_null()).select(
        "config", "base_id", "metric", pl.col("value").alias("base_value")
    )
    variants = ok.filter(pl.col("perturbation").is_not_null())
    paired = variants.join(base, on=["config", "base_id", "metric"], how="inner")
    return paired.select(
        *KEYS,
        "base_id",
        "cluster_id",
        (pl.col("value") - pl.col("base_value")).alias("diff"),
        "closed_book",
    ).sort([*KEYS, "base_id"])


def drop_table(
    diffs: pl.DataFrame, *, n_resamples: int, seed: int, exclude_closed_book: bool = False
) -> pl.DataFrame:
    """Return one row per config x perturbation x metric: drop, 95 % CI, one-sided p, counts.

    Args:
        diffs: output of :func:`paired_diffs`.
        n_resamples: bootstrap replicates.
        seed: seed of the one ``numpy.random.Generator`` used for all cells, in sorted order.
        exclude_closed_book: leave out cases tagged ``closed_book_answerable``.

    Returns:
        ``config, perturbation, metric, drop, ci_low, ci_high, p, n_cases, n_clusters``,
        sorted by the keys.
    """
    if exclude_closed_book:
        diffs = diffs.filter(~pl.col("closed_book"))
    rng = np.random.default_rng(seed)
    per_cluster = (
        diffs.group_by([*KEYS, "cluster_id"])
        .agg(pl.col("diff").mean(), pl.len().alias("cases"))
        .sort([*KEYS, "cluster_id"])
    )
    rows = []
    for key, clusters in per_cluster.partition_by(KEYS, as_dict=True, maintain_order=True).items():
        result = paired_cluster_bootstrap(
            clusters["diff"].to_numpy().astype(np.float64),
            clusters["cluster_id"].to_numpy().astype(np.str_),
            n_resamples=n_resamples,
            confidence=0.95,
            rng=rng,
        )
        rows.append(
            {
                **dict(zip(KEYS, key, strict=True)),
                "drop": result.mean_diff,
                "ci_low": result.ci_low,
                "ci_high": result.ci_high,
                "p": result.p_value,
                "n_cases": int(clusters["cases"].sum()),
                "n_clusters": clusters.height,
            }
        )
    return pl.DataFrame(rows).sort(KEYS)


def fix_first(table: pl.DataFrame, *, q: float = FIX_FIRST_Q, top: int = 5) -> pl.DataFrame:
    """Rank the drops that survive Benjamini-Hochberg at ``q`` over all cells, largest first.

    Args:
        table: output of :func:`drop_table` (all cells, so the correction sees every test).
        q: false discovery rate.
        top: length of the list.

    Returns:
        The surviving cells with a negative drop, ``p_bh`` added, at most ``top`` rows.
    """
    adjusted = table.with_columns(pl.Series("p_bh", bh_adjust(table["p"].to_list())))
    keep = adjusted.filter((pl.col("p_bh") < q) & (pl.col("drop") < 0))
    return keep.sort(["drop", *KEYS]).head(top)


def write_heatmap(table: pl.DataFrame, metric: str, path: Path) -> Path:
    """Write the perturbation x config heatmap of ``metric``'s drops as a PNG.

    Returns:
        ``path``.
    """
    cells = table.filter(pl.col("metric") == metric)
    perturbations = sorted(cells["perturbation"].unique().to_list())
    configs = sorted(cells["config"].unique().to_list())
    grid = np.full((len(perturbations), len(configs)), np.nan)
    for row in cells.iter_rows(named=True):
        grid[perturbations.index(row["perturbation"]), configs.index(row["config"])] = row["drop"]
    fig, ax = plt.subplots(figsize=(1.2 + 0.9 * len(configs), 1.0 + 0.45 * len(perturbations)))
    image = ax.imshow(grid, cmap="RdBu", vmin=-0.3, vmax=0.3, aspect="auto")
    ax.set_xticks(range(len(configs)), configs, rotation=45, ha="right")
    ax.set_yticks(range(len(perturbations)), perturbations)
    ax.set_title(f"RQ1 drop of {metric} (perturbed - base)")
    fig.colorbar(image, ax=ax)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=120, metadata={"Software": None})
    plt.close(fig)
    return path
