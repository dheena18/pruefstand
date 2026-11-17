"""T6.3 S5 (offline): paired diffs from run pairs and the ``results/noise`` output files.

* ``paired_diffs``: one row per paired case diff of a run pair, made with the gate's own pairing
  (``gate.tables.pair_runs``, worst-fill, judge-error flags) and slices (``gate.slices``, X3.6:
  perturbed cases only in ``perturbed_all``); columns ``arm, kind, pair, split, metric, slice,
  cluster_id, diff`` (diff oriented so that negative = worse), the input of ``analyze.py``.
* ``mde_rows``: one row per gated metric x gated slice x split with the columns of the T6.3
  prompt (``sigma_d_noop`` = replay, ``sigma_d_churn`` = MDE sizing, ``sigma_d_repeat`` = floor).
* writers for ``sigma.csv``, ``mde.csv`` (one row per metric x slice x split, refused otherwise),
  ``replay.csv`` (column ``arm``), ``timings.csv`` and ``paired_diffs.parquet`` (< 1 MB).
"""

from collections.abc import Mapping, Sequence
from pathlib import Path

import numpy as np
import polars as pl
from noise.analyze import mde, mde_row, sigma_table
from noise.replay import ReplayResult

from pruefstand.core.config.gate import GatePolicy
from pruefstand.core.errors import ConfigError
from pruefstand.core.models.run import RunResults
from pruefstand.gate.slices import slice_members, slice_specs
from pruefstand.gate.tables import pair_runs

MDE_COLUMNS = [
    "metric", "slice", "split", "sigma_d_noop", "sigma_d_churn", "sigma_d_repeat",
    "n_applicable_clusters", "gated", "m_family", "detectable_drop", "detectable_drop_noop",
    "delta", "detectable_le_1_5delta", "clusters_needed",
]  # fmt: skip
MAX_PARQUET_BYTES = 1_000_000


def slice_label(dimension: str, value: str) -> str:
    """``overall`` and ``perturbed_all`` as they are, else ``<dimension>=<value>``.

    Examples:
        >>> slice_label("overall", "overall"), slice_label("tenant", "kanzlei_mueller")
        ('overall', 'tenant=kanzlei_mueller')
    """
    return dimension if dimension == value else f"{dimension}={value}"


def paired_diffs(
    baseline: RunResults,
    candidate: RunResults,
    policy: GatePolicy,
    *,
    directions: Mapping[str, bool],
    arm: str,
    kind: str,
    pair: str,
    split: str,
) -> pl.DataFrame:
    """The paired case diffs of every ``max_drop`` metric on every gated slice of one run pair."""
    frames = []
    for metric, rule in policy.metrics.items():
        if rule.max_drop is None:
            continue
        table = pair_runs(baseline, candidate, metric, higher_is_better=directions[metric])
        for dimension, value in slice_specs(table, policy):
            if dimension not in policy.gated_slices:
                continue
            mask = slice_members(table, dimension, value)
            frames.append(
                pl.DataFrame({
                    "cluster_id": table.cluster_ids[mask].astype(str),
                    "diff": np.asarray(table.diffs[mask], dtype=float),
                }).with_columns(
                    pl.lit(arm).alias("arm"), pl.lit(kind).alias("kind"),
                    pl.lit(pair).alias("pair"), pl.lit(split).alias("split"),
                    pl.lit(metric).alias("metric"),
                    pl.lit(slice_label(dimension, value)).alias("slice"),
                )
            )  # fmt: skip
    columns = ["arm", "kind", "pair", "split", "metric", "slice", "cluster_id", "diff"]
    return pl.concat(frames).select(columns) if frames else pl.DataFrame(schema=columns)


def _sigma(sigma: pl.DataFrame, arm: str, metric: str, slice_: str) -> float | None:
    row = sigma.filter(
        (pl.col("arm") == arm) & (pl.col("kind") == "all")
        & (pl.col("metric") == metric) & (pl.col("slice") == slice_)
    )  # fmt: skip
    return None if row.is_empty() else float(row["sigma_d"][0])


def mde_rows(diffs: pl.DataFrame, policy: GatePolicy, split: str) -> list[dict[str, object]]:
    """The ``mde.csv`` rows of one split: every metric x slice with a churn sigma_d.

    ``n_applicable_clusters`` is the measured cluster count of the slice (all pairs of the split);
    ``m_family`` the number of gated rows (the run's one Holm family); the detectable drop and the
    1.5 delta check use sigma_d(churn), ``detectable_drop_noop`` sigma_d(no-op).

    Raises:
        ConfigError: the split has no diffs.
    """
    part = diffs.filter(pl.col("split") == split)
    if part.is_empty():
        msg = f"no paired diffs for split {split}"
        raise ConfigError(msg)
    sigma = sigma_table(part)
    counts = part.group_by(["metric", "slice"]).agg(pl.col("cluster_id").n_unique().alias("k"))
    keys = sorted((r["metric"], r["slice"], r["k"]) for r in counts.iter_rows(named=True))
    m_family = sum(k >= policy.min_clusters for _, _, k in keys)
    m = max(m_family, 1)
    rows = []
    for metric, slice_, k in keys:
        churn = _sigma(sigma, "churn", metric, slice_)
        sized = None if churn is None else mde_row((metric, slice_), churn, k, policy, m_family=m)
        if sized is None:
            continue
        noop = _sigma(sigma, "noop", metric, slice_)
        rows.append({
            "metric": metric, "slice": slice_, "split": split,
            "sigma_d_noop": noop, "sigma_d_churn": churn,
            "sigma_d_repeat": _sigma(sigma, "repeat", metric, slice_),
            "n_applicable_clusters": k, "gated": sized["gated"], "m_family": m_family,
            "detectable_drop": sized["mde"],
            "detectable_drop_noop": None if noop is None
            else mde(noop, k, policy, float(sized["delta"]), m),  # type: ignore[arg-type]  # a float from mde_row
            "delta": sized["delta"], "detectable_le_1_5delta": sized["ok"],
            "clusters_needed": sized["clusters_needed"],
        })  # fmt: skip
    return rows


def write_mde(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    """Write ``mde.csv``; refuse a second row for one metric x slice x split.

    Raises:
        ConfigError: a duplicate key.
    """
    seen: set[tuple[object, object, object]] = set()
    for row in rows:
        key = (row["metric"], row["slice"], row["split"])
        if key in seen:
            msg = f"mde.csv: more than one row for {key}"
            raise ConfigError(msg)
        seen.add(key)
    _write(path, pl.DataFrame(list(rows), schema=MDE_COLUMNS, orient="row") if rows
           else pl.DataFrame(schema=MDE_COLUMNS))  # fmt: skip


def write_sigma(path: Path, diffs: pl.DataFrame) -> None:
    """Write ``sigma.csv``: sigma_d per split, arm, kind, metric and slice (``all`` = pooled)."""
    parts = [
        sigma_table(diffs.filter(pl.col("split") == s)).with_columns(pl.lit(s).alias("split"))
        for s in sorted(set(diffs["split"]))
    ]
    _write(path, pl.concat(parts).sort(["split", "arm", "kind", "metric", "slice"]))


def replay_rows(arm: str, result: ReplayResult) -> dict[str, object]:
    """One ``replay.csv`` row of an arm (FAIL and WARN-or-FAIL rates with Wilson 95 % CIs)."""
    return {
        "arm": arm, "n": result.n,
        "fail": result.fail, "fail_rate": result.fail / result.n,
        "fail_ci_low": result.fail_ci[0], "fail_ci_high": result.fail_ci[1],
        "warn_or_fail": result.warn_or_fail, "warn_or_fail_rate": result.warn_or_fail / result.n,
        "warn_or_fail_ci_low": result.warn_or_fail_ci[0],
        "warn_or_fail_ci_high": result.warn_or_fail_ci[1],
    }  # fmt: skip


def write_rows(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    """Write ``replay.csv`` or ``timings.csv`` from rows of one shape."""
    _write(path, pl.DataFrame(list(rows)))


def timing_row(stage: str, seconds: float, budget_s: float | None) -> dict[str, object]:
    """One ``timings.csv`` row; ``within_budget`` is null for a stage without a budget."""
    return {
        "stage": stage, "seconds": seconds, "budget_s": budget_s,
        "within_budget": None if budget_s is None else seconds <= budget_s,
    }  # fmt: skip


def write_paired_diffs(path: Path, diffs: pl.DataFrame) -> int:
    """Write ``paired_diffs.parquet`` (zstd) and return its size.

    Raises:
        ConfigError: the file is 1 MB or more (it is committed for T7.4's hosted check).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    diffs.write_parquet(path, compression="zstd", compression_level=19)
    size = path.stat().st_size
    if size >= MAX_PARQUET_BYTES:
        path.unlink()
        msg = f"{path}: {size} bytes, the committed input must stay below 1 MB"
        raise ConfigError(msg)
    return size


def _write(path: Path, frame: pl.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.write_csv(path)
