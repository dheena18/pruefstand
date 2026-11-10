"""``calibration_table`` (``build_table``): one row per judge x metric x set x stratum (T5.4).

D9-28.

Binarisation: a label or judge score counts as positive iff it is the metric's top raw score
(``judges.output.SPECS[metric].max_raw``: "2 vs < 2" on 3-point metrics, the raw label on binary
ones). Kappa and AC1 are computed only on strata that hold both labels; a single-label stratum
(every hard negative is a negative) reports them as null and is judged by specificity (X1.1).
"""

import math
from collections.abc import Callable

import numpy as np
import polars as pl

from pruefstand.judges import calibration as cal
from pruefstand.judges.output import spec_of

BOOTSTRAP_RESAMPLES = 2_000
BOOTSTRAP_SEED = 1234
CONFIDENCE = 0.95
STRATA: dict[str, Callable[[pl.DataFrame], pl.DataFrame]] = {
    "all": lambda df: df,
    "hard_negative": lambda df: df.filter(pl.col("hard_negative")),
    "memerag_not_supported": lambda df: df.filter(pl.col("hard_type") == "memerag_not_supported"),
}
COST_COLUMNS = (
    "usd_per_1k",
    "gpu_s_per_1k",
    "quota_requests_per_1k",
    "latency_p50_ms",
    "latency_p95_ms",
)
LABEL_COLUMNS = (
    "item_id",
    "label_set",
    "metric",
    "label",
    "cluster_id",
    "hard_negative",
    "label_origin",
)
VERDICT_COLUMNS = ("item_id", "judge", "metric", "score")


def _nan_to_none(value: float) -> float | None:
    return None if math.isnan(value) else value


def _kappa(df: pl.DataFrame) -> float:
    return cal.cohens_kappa(df["y"].to_list(), df["p"].to_list())


def _binarised(labels: pl.DataFrame, verdicts: pl.DataFrame) -> pl.DataFrame:
    missing = [c for c in LABEL_COLUMNS if c not in labels.columns]
    missing += [c for c in VERDICT_COLUMNS if c not in verdicts.columns]
    if missing:
        msg = f"calibration_table: missing columns {missing}"
        raise ValueError(msg)
    if "hard_type" not in labels.columns:
        labels = labels.with_columns(pl.lit(None, dtype=pl.String).alias("hard_type"))
    joined = labels.join(
        verdicts.drop_nulls("score"), on=["item_id", "metric"], how="inner", validate="1:m"
    )
    top = pl.col("metric").map_elements(lambda m: spec_of(m).max_raw, return_dtype=pl.Int64)
    return joined.with_columns(
        (pl.col("label") == top).cast(pl.Int64).alias("y"),
        (pl.col("score") == top).cast(pl.Int64).alias("p"),
    )


def _row(df: pl.DataFrame) -> dict[str, object]:
    y = df["y"].to_numpy()
    p = df["p"].to_numpy()
    two_labels = len(set(y.tolist())) == 2
    row: dict[str, object] = {
        "n": df.height,
        "n_clusters": df["cluster_id"].n_unique(),
        "prevalence": float(y.mean()),
        "accuracy": float((y == p).mean()),
        "kappa": None,
        "kappa_ci_low": None,
        "kappa_ci_high": None,
        "ac1": None,
        "balanced_accuracy": None,
        "specificity": None,
        "specificity_ci_low": None,
    }
    if (y == 0).any():
        tnr, low, _ = cal.specificity(y.tolist(), p.tolist())
        row["specificity"], row["specificity_ci_low"] = tnr, low
    if two_labels:
        sens = float((p[y == 1] == 1).mean())
        row["balanced_accuracy"] = (sens + float(row["specificity"] or 0.0)) / 2.0  # type: ignore[arg-type]  # set above: y holds a 0
        row["kappa"] = _nan_to_none(_kappa(df))
        row["ac1"] = _nan_to_none(cal.gwet_ac1(y.tolist(), p.tolist()))
        low, high = cal.cluster_bootstrap_ci(
            _kappa,
            df,
            "cluster_id",
            BOOTSTRAP_RESAMPLES,
            CONFIDENCE,
            np.random.default_rng(BOOTSTRAP_SEED),
        )
        row["kappa_ci_low"], row["kappa_ci_high"] = _nan_to_none(low), _nan_to_none(high)
    rho = cal.spearman(df["label"].to_list(), df["score"].to_list())
    row["spearman"] = _nan_to_none(rho)
    return row


def build_table(labels: pl.DataFrame, verdicts: pl.DataFrame) -> pl.DataFrame:
    """Agreement of every judge with the gold labels, per metric, label set and stratum.

    Args:
        labels: One row per item: ``item_id, label_set, metric, label`` (raw), ``cluster_id``,
            ``hard_negative``, ``label_origin`` (``human`` | ``construction``), optional
            ``hard_type``.
        verdicts: One row per judged item: ``item_id, judge, metric, score`` (raw judge score;
            null = failed call, left out). Optional per-judge cost columns (``usd_per_1k`` ...,
            see ``COST_COLUMNS``) are copied onto the judge's rows; ``discrimination`` is left
            null here and filled by the RQ2 report from the degraded pairs.

    Returns:
        Columns ``judge, metric, label_set, stratum, label_origin, n, n_clusters, prevalence,
        kappa, kappa_ci_low, kappa_ci_high, accuracy, balanced_accuracy, specificity,
        specificity_ci_low, ac1, spearman, discrimination`` plus ``COST_COLUMNS``; label sets
        are never pooled. Kappa CIs: cluster bootstrap, 2 000 resamples, seed 1234.

    Raises:
        ValueError: A required column is missing.
    """
    joined = _binarised(labels, verdicts)
    rows: list[dict[str, object]] = []
    keys = ["judge", "metric", "label_set", "label_origin"]
    for key, group in joined.sort(keys).group_by(keys, maintain_order=True):
        for stratum, pick in STRATA.items():
            part = pick(group)
            if part.height == 0:
                continue
            judge, metric, label_set, origin = key
            rows.append(
                {
                    "judge": judge,
                    "metric": metric,
                    "label_set": label_set,
                    "stratum": stratum,
                    "label_origin": origin,
                    **_row(part),
                    "discrimination": None,
                }
            )
    table = pl.DataFrame(rows, infer_schema_length=None)
    costs = [c for c in COST_COLUMNS if c in verdicts.columns]
    if costs and table.height:
        per_judge = verdicts.group_by("judge").agg(pl.col(c).first() for c in costs)
        table = table.join(per_judge, on="judge", how="left")
    for col in COST_COLUMNS:
        if col not in table.columns:
            table = table.with_columns(pl.lit(None, dtype=pl.Float64).alias(col))
    return table
