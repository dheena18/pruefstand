"""``results/rq2/bias.csv`` from the bias rows of ``bias.py`` (T5.4 S6)."""

import polars as pl
from rq2.bias import AXES, FLAG, bias_delta
from rq2.rq2_config import REPO, RQ2Config, slug


def bias_table(cfg: RQ2Config) -> pl.DataFrame:
    """One row per judge and axis: changed pairs, Delta, CI, flag (|Delta| > 0.05)."""
    rows: list[dict[str, object]] = []
    for judge in cfg.judges:
        path = REPO / cfg.out_dir / f"bias_{slug(judge.id)}.parquet"
        if not path.is_file():
            continue
        data = pl.read_parquet(path)
        for axis in AXES:
            part = data.filter((pl.col("axis") == axis) & pl.col("changed")).drop_nulls(
                ["base", "perturbed"]
            )
            row: dict[str, object] = {
                "judge": judge.id,
                "axis": axis,
                "n_items": data.filter(pl.col("axis") == axis).height,
                "n_changed": part.height,
                "delta": None,
                "ci_low": None,
                "ci_high": None,
                "flag": None,
            }
            if part.height:
                delta, low, high = bias_delta(part, cfg.seed)
                row.update(delta=delta, ci_low=low, ci_high=high, flag=abs(delta) > FLAG)
            rows.append(row)
    return pl.DataFrame(rows, infer_schema_length=None)
