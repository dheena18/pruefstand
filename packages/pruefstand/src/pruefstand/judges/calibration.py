"""Judge calibration statistics (T5.4, interfaces §6): pure functions, numpy/scipy/polars only.

Agreement of a judge with gold labels: Cohen's kappa (binary or weighted), Gwet's AC1, Spearman,
specificity with its Wilson interval and a cluster bootstrap. ``calibration_table`` delegates to
``judges/calibration_table.py``, as are the status-file readers of T5.2b
(``judges/status.py``), so ``judges.calibration`` stays the one import path of interfaces §6.
"""

import math
import warnings
from collections.abc import Callable, Sequence
from typing import Literal

import numpy as np
import polars as pl
from scipy import stats

from pruefstand.judges.status import (
    CalibrationStatus,
    judges_uncalibrated,
    read_status,
    refusal_judge_passed,
)

__all__ = [
    "CalibrationStatus",
    "calibration_table",
    "cluster_bootstrap_ci",
    "cohens_kappa",
    "gwet_ac1",
    "judges_uncalibrated",
    "read_status",
    "refusal_judge_passed",
    "spearman",
    "specificity",
    "wilson_interval",
]

Z95 = 1.959963984540054


def _check(a: Sequence[float], b: Sequence[float]) -> None:
    if len(a) != len(b):
        msg = f"rater vectors differ in length ({len(a)} vs {len(b)})"
        raise ValueError(msg)
    if not a:
        msg = "rater vectors are empty"
        raise ValueError(msg)


def _undefined(name: str) -> float:
    warnings.warn(f"{name} is undefined when chance agreement is 1", UserWarning, stacklevel=3)
    return math.nan


def cohens_kappa(
    a: Sequence[int], b: Sequence[int], weights: Literal[None, "linear", "quadratic"] = None
) -> float:
    """Cohen's kappa of two raters (binary, or weighted on an ordinal scale).

    Args:
        a: Ratings of rater A (e.g. the gold labels).
        b: Ratings of rater B (e.g. the judge), same length.
        weights: None (nominal), ``linear`` or ``quadratic`` (distance over the observed range).

    Returns:
        Kappa in [-1, 1]; ``nan`` with a ``UserWarning`` when chance agreement is 1 (both raters
        constant on the same value: kappa is undefined).

    Raises:
        ValueError: Empty vectors or different lengths.

    Examples:
        p_o = 0.75, p_e = 0.5 * 0.25 + 0.5 * 0.75 = 0.5, kappa = (0.75 - 0.5) / 0.5:

        >>> cohens_kappa([1, 1, 0, 0], [1, 0, 0, 0])
        0.5
    """
    _check(a, b)
    cats = sorted(set(a) | set(b))
    index = {c: i for i, c in enumerate(cats)}
    k = len(cats)
    observed = np.zeros((k, k))
    for x, y in zip(a, b, strict=True):
        observed[index[x], index[y]] += 1.0
    observed /= observed.sum()
    expected = np.outer(observed.sum(axis=1), observed.sum(axis=0))
    values = np.asarray(cats, dtype=float)
    span = values[-1] - values[0] if k > 1 else 1.0
    dist = np.abs(values[:, None] - values[None, :]) / span
    weight = {None: (dist > 0).astype(float), "linear": dist, "quadratic": dist**2}[weights]
    denom = float((weight * expected).sum())
    if denom == 0.0:
        return _undefined("kappa")
    return round(1.0 - float((weight * observed).sum()) / denom, 12)


def gwet_ac1(a: Sequence[int], b: Sequence[int]) -> float:
    """Gwet's AC1 of two raters: agreement robust to skewed prevalence.

    ``p_e = 1 / (q - 1) * sum_k pi_k (1 - pi_k)`` with ``pi_k`` the mean share of category k over
    both raters and q the number of observed categories.

    Args:
        a: Ratings of rater A.
        b: Ratings of rater B, same length.

    Returns:
        AC1; ``nan`` with a ``UserWarning`` when only one category occurs.

    Raises:
        ValueError: Empty vectors or different lengths.

    Examples:
        pi_1 = 0.375, p_e = 2 * 0.375 * 0.625 = 0.46875, AC1 = (0.75 - 0.46875) / 0.53125:

        >>> round(gwet_ac1([1, 1, 0, 0], [1, 0, 0, 0]), 6)
        0.529412
    """
    _check(a, b)
    cats = sorted(set(a) | set(b))
    if len(cats) < 2:
        return _undefined("AC1")
    arr_a, arr_b = np.asarray(a), np.asarray(b)
    p_o = float(np.mean(arr_a == arr_b))
    pi = np.array([(np.mean(arr_a == c) + np.mean(arr_b == c)) / 2.0 for c in cats])
    p_e = float((pi * (1.0 - pi)).sum()) / (len(cats) - 1)
    return (p_o - p_e) / (1.0 - p_e)


def spearman(a: Sequence[float], b: Sequence[float]) -> float:
    """Spearman rank correlation (ties get average ranks).

    Returns:
        rho in [-1, 1]; ``nan`` when one side is constant.

    Raises:
        ValueError: Empty vectors or different lengths.

    Examples:
        >>> round(spearman([1, 1, 2], [1, 2, 3]), 3)
        0.866
    """
    _check(a, b)
    if len(set(a)) < 2 or len(set(b)) < 2:
        return math.nan
    return float(stats.spearmanr(a, b).statistic)


def wilson_interval(successes: int, n: int, z: float = Z95) -> tuple[float, float]:
    """Wilson score interval of a proportion (95 % by default).

    Raises:
        ValueError: ``n < 1`` or ``successes`` outside ``[0, n]``.

    Examples:
        >>> tuple(round(x, 3) for x in wilson_interval(24, 30))
        (0.627, 0.905)
    """
    if n < 1 or not 0 <= successes <= n:
        msg = f"need 0 <= successes <= n and n >= 1 (got {successes}/{n})"
        raise ValueError(msg)
    p = successes / n
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def specificity(labels: Sequence[int], preds: Sequence[int]) -> tuple[float, float, float]:
    """True-negative rate on binary labels (0 = negative) with its 95 % Wilson interval (X1.1).

    Args:
        labels: Binary gold labels.
        preds: Binary judge decisions, same length.

    Returns:
        ``(tnr, wilson_low, wilson_high)``.

    Raises:
        ValueError: Different lengths, or no negative label.

    Examples:
        125 of 150 hard negatives rejected:

        >>> tuple(round(x, 3) for x in specificity([0] * 150, [0] * 125 + [1] * 25))
        (0.833, 0.766, 0.884)
    """
    if len(labels) != len(preds):
        msg = f"labels and preds differ in length ({len(labels)} vs {len(preds)})"
        raise ValueError(msg)
    negatives = [p for lab, p in zip(labels, preds, strict=True) if lab == 0]
    if not negatives:
        msg = "specificity needs at least one negative label"
        raise ValueError(msg)
    hits = sum(1 for p in negatives if p == 0)
    low, high = wilson_interval(hits, len(negatives))
    return hits / len(negatives), low, high


def cluster_bootstrap_ci(  # noqa: PLR0917 - signature fixed in interfaces §6
    stat: Callable[[pl.DataFrame], float],
    df: pl.DataFrame,
    cluster_col: str,
    n_resamples: int,
    confidence: float,
    rng: np.random.Generator,
) -> tuple[float, float]:
    """Percentile CI of ``stat`` resampling whole clusters with replacement.

    Resamples where ``stat`` is ``nan`` (e.g. kappa on a one-label draw) are dropped.

    Args:
        stat: Statistic of a frame.
        df: The rows.
        cluster_col: Column whose values form the clusters (``cluster_id``).
        n_resamples: Bootstrap draws (2 000 in T5.4).
        confidence: Two-sided level, e.g. 0.95.
        rng: Seeded generator (1234 in T5.4).

    Returns:
        ``(low, high)``; ``(nan, nan)`` when every draw is ``nan``.

    Raises:
        ValueError: Empty frame, ``n_resamples < 1`` or ``confidence`` outside (0, 1).

    Examples:
        >>> df = pl.DataFrame({"c": [1, 1, 2, 2, 3, 3], "x": [1, 1, 0, 0, 1, 0]})
        >>> mean = lambda d: float(d["x"].to_numpy().mean())
        >>> low, high = cluster_bootstrap_ci(mean, df, "c", 200, 0.95, np.random.default_rng(1234))
        >>> 0.0 <= low <= 0.5 <= high <= 1.0
        True
    """
    if df.height == 0 or n_resamples < 1 or not 0.0 < confidence < 1.0:
        msg = "need rows, n_resamples >= 1 and 0 < confidence < 1"
        raise ValueError(msg)
    groups = df.with_row_index("_row").group_by(cluster_col, maintain_order=True).agg("_row")
    members = [np.asarray(rows, dtype=np.int64) for rows in groups["_row"].to_list()]
    values: list[float] = []
    for _ in range(n_resamples):
        picks = rng.integers(0, len(members), size=len(members))
        idx = np.concatenate([members[i] for i in picks])
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            values.append(float(stat(df[idx])))
    arr = np.asarray(values)
    arr = arr[~np.isnan(arr)]
    if arr.size == 0:
        return math.nan, math.nan
    tail = (1.0 - confidence) / 2.0 * 100.0
    low, high = np.percentile(arr, [tail, 100.0 - tail])
    return float(low), float(high)


def calibration_table(labels: pl.DataFrame, verdicts: pl.DataFrame) -> pl.DataFrame:
    """One row per judge x metric x label set x stratum (``calibration_table.build_table``).

    Args:
        labels: Items with gold labels (see ``build_table``).
        verdicts: Judge scores per item (see ``build_table``).

    Returns:
        The table of interfaces §6; kappa/AC1 null on single-label strata.

    Raises:
        ValueError: A required column is missing.
    """
    from pruefstand.judges.calibration_table import build_table  # noqa: PLC0415 - avoids a cycle

    return build_table(labels, verdicts)
