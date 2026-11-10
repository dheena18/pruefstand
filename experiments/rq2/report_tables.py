"""Computations of the RQ2 report (T5.4 S4/S5/S7): labels, costs, discrimination, agreement."""

from collections.abc import Sequence

import numpy as np
import polars as pl
from rq2.calib_schema import CalibrationItem
from rq2.pass_rule import SetEvidence

from pruefstand.judges.calibration import cohens_kappa
from pruefstand.judges.output import spec_of

#: Human-human ceiling per label set (S5). MEMERAG: the inter-annotator agreement reported by the
#: MEMERAG paper (Cruz Blandón et al., ACL 2025, arXiv:2502.17163, Table 2) for German coarse
#: faithfulness: Gwet AC1 0.84, Fleiss kappa 0.81 (3 annotators, 10 questions); constructed sets:
# none.
CEILING: dict[str, str] = {
    "memerag": "AC1 0.84 / Fleiss kappa 0.81 (DE, MEMERAG Table 2, 3 annotators x 10 questions)",
    "faithfulness_constructed": "n/a (labels by construction)",
    "correctness": "n/a (labels by construction)",
    "refusal": "n/a (labels by construction)",
    "consistency": "n/a (labels by construction)",
    "legal_hard": "n/a (labels by construction)",
}


def label_frame(items: Sequence[tuple[str, str, CalibrationItem]]) -> pl.DataFrame:
    """One row per ``(set name, origin, item)``: the label columns of ``calibration_table``."""
    return pl.DataFrame(
        {
            "item_id": [i.item_id for _, _, i in items],
            "label_set": [s for s, _, _ in items],
            "metric": [i.metric for _, _, i in items],
            "label": [i.label for _, _, i in items],
            "cluster_id": [i.cluster_id for _, _, i in items],
            "hard_negative": [i.hard_negative for _, _, i in items],
            "hard_type": [i.hard_type for _, _, i in items],
            "label_origin": [o for _, o, _ in items],
        },
        schema_overrides={"hard_type": pl.String},
    )


def cost_columns(calls: pl.DataFrame, judge: str, concurrency: int) -> dict[str, float | None]:
    """Cost per 1 000 judgments from the uncached calls of one judge (S4).

    GPU-seconds of a local judge = summed call latency / concurrency (calls overlap on one GPU);
    quota requests of a hosted judge = calls per judgment x 1 000.
    """
    real = calls.filter(~pl.col("cached") & pl.col("error").is_null())
    if real.height == 0:
        return dict.fromkeys(
            (
                "usd_per_1k",
                "gpu_s_per_1k",
                "quota_requests_per_1k",
                "latency_p50_ms",
                "latency_p95_ms",
            )
        )
    lat = real["latency_ms"].to_numpy()
    local = judge.startswith("ollama/")
    return {
        "usd_per_1k": float(real["cost_usd"].sum()) / real.height * 1000.0,
        "gpu_s_per_1k": float(lat.sum()) / 1000.0 / concurrency / real.height * 1000.0
        if local
        else None,
        "quota_requests_per_1k": None if local else 1000.0 * calls.height / real.height,
        "latency_p50_ms": float(np.percentile(lat, 50)),
        "latency_p95_ms": float(np.percentile(lat, 95)),
    }


def discrimination_table(pairs: pl.DataFrame) -> pl.DataFrame:
    """Share of pairs with a strictly lower degraded score, per judge, set, metric and edit."""
    scored = pairs.drop_nulls(["base", "degraded"])
    return (
        scored.group_by(["judge", "label_set", "metric", "edit"])
        .agg(
            pl.len().alias("n"),
            (pl.col("degraded") < pl.col("base")).mean().alias("discrimination"),
            (pl.col("base") == pl.col("base").max()).mean().alias("base_top_share"),
        )
        .sort(["judge", "label_set", "edit"])
    )


def evidence(table: pl.DataFrame, judge: str, metric: str, label_set: str) -> SetEvidence | None:
    """Pass-rule evidence of one gating set (None when it was not evaluated)."""
    rows = table.filter(
        (pl.col("judge") == judge)
        & (pl.col("metric") == metric)
        & (pl.col("label_set") == label_set)
    )
    full = rows.filter(pl.col("stratum") == "all")
    if full.height == 0 or not full["n"][0]:
        return None
    hard = rows.filter(pl.col("stratum") == "hard_negative")
    spec = hard["specificity"][0] if hard.height else None
    low = hard["specificity_ci_low"][0] if hard.height else None
    return SetEvidence(full["kappa"][0], spec, low)


def agreement_matrix(verdicts: pl.DataFrame) -> pl.DataFrame:
    """Binary kappa between every two judges on the items both scored (S5), plus the ceiling."""
    judges = sorted(verdicts["judge"].unique().to_list())
    rows: list[dict[str, object]] = []
    for label_set, part in verdicts.drop_nulls("score").group_by("label_set"):
        name = str(label_set[0])
        for a in judges:
            for b in judges:
                pa = part.filter(pl.col("judge") == a).select(
                    "item_id", "metric", pl.col("score").alias("sa")
                )
                pb = part.filter(pl.col("judge") == b).select(
                    "item_id", pl.col("score").alias("sb")
                )
                common = pa.join(pb, on="item_id")
                if common.height == 0:
                    continue
                top = [spec_of(m).max_raw for m in common["metric"].to_list()]
                xa = [int(s == t) for s, t in zip(common["sa"].to_list(), top, strict=True)]
                xb = [int(s == t) for s, t in zip(common["sb"].to_list(), top, strict=True)]
                kappa = 1.0 if a == b else cohens_kappa(xa, xb)
                rows.append(
                    {
                        "label_set": name,
                        "judge_a": a,
                        "judge_b": b,
                        "n_common": common.height,
                        "kappa": kappa,
                        "ceiling": CEILING.get(name, "n/a"),
                    }
                )
    return pl.DataFrame(rows, infer_schema_length=None).sort(["label_set", "judge_a", "judge_b"])
