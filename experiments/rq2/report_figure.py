"""``results/rq2/cost_vs_kappa.png``: GPU-seconds per 1 000 judgments vs binary kappa (T5.4 S7)."""

from pathlib import Path

import matplotlib as mpl

mpl.use("Agg")
import matplotlib.pyplot as plt
import polars as pl


def cost_vs_kappa(table: pl.DataFrame, path: Path) -> None:
    """One point per judge and label set (``all`` stratum, evaluated rows with a kappa)."""
    rows = table.filter((pl.col("stratum") == "all") & pl.col("kappa").is_not_null())
    fig, ax = plt.subplots(figsize=(6, 4))
    for row in rows.iter_rows(named=True):
        cost = row.get("gpu_s_per_1k") or row.get("quota_requests_per_1k") or 0.0
        ax.scatter(cost, row["kappa"], color="#3b6ea5")
        ax.annotate(
            f"{row['judge'].split('/')[-1]} {row['label_set']}", (cost, row["kappa"]), fontsize=7
        )
    ax.axhline(0.6, color="#b03a2e", linestyle="--", linewidth=1, label="pass rule kappa 0.6")
    ax.set_xlabel("GPU-s (local) / quota requests (hosted) per 1 000 judgments")
    ax.set_ylabel("binary kappa (judge 2 vs < 2), test split")
    ax.legend(loc="lower right", fontsize=7)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=120, metadata={"Software": None})
    plt.close(fig)
