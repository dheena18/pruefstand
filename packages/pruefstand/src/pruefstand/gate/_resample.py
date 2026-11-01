"""Helpers of the paired cluster bootstrap: argument checks, the small-sample factor, resampling."""

import math

import numpy as np
from numpy.typing import NDArray

from pruefstand.gate._validate import (
    as_float_vector,
    check_instance,
    check_int,
    check_open_unit,
    fail,
    z_upper,
)

MAX_RESAMPLES = 10_000_000  # same cap as GatePolicy.n_resamples; bounds the work of one call
MAX_INDEX_ELEMENTS = 50_000_000  # largest resample index array held in memory at once
MAX_DRAWS = 10_000_000_000  # n_resamples * n_clusters: bounds the CPU time of one call


def small_sample_factor(k: int, alpha: float) -> float:
    """Return c_k = sqrt(k/(k-1)) * t_{k-1, 1-alpha} / z_{1-alpha}; 1.0 for k < 2.

    Examples:
        >>> round(small_sample_factor(30, 0.025), 3)
        1.061
        >>> round(small_sample_factor(300, 0.025), 3)
        1.006
    """
    if k < 2:
        return 1.0
    from scipy.special import stdtrit  # noqa: PLC0415  (lazy: scipy is slow to import)

    t = -float(stdtrit(k - 1, alpha))  # upper-tail quantile t_{k-1, 1-alpha}
    return math.sqrt(k / (k - 1)) * t / z_upper(alpha)


def validate_bootstrap(
    diffs: NDArray[np.float64],
    clusters: NDArray[np.str_],
    n_resamples: int,
    confidence: float,
    alpha: float,
) -> tuple[NDArray[np.float64], NDArray[np.str_]]:
    d = as_float_vector("diffs", diffs)
    c = np.asarray(clusters)
    if c.ndim != 1 or c.dtype.kind != "U":
        fail("clusters must be a one-dimensional array of strings")
    if d.size == 0 or d.size != c.size:
        fail("diffs and clusters must be non-empty and of equal length")
    if (np.char.str_len(c) == 0).any():
        fail("cluster ids must be non-empty strings")
    check_int("n_resamples", n_resamples, 1)
    if n_resamples > MAX_RESAMPLES:
        fail(f"n_resamples must be <= {MAX_RESAMPLES}, got {n_resamples}")
    check_open_unit("confidence", confidence)
    check_open_unit("alpha", alpha, 0.5)
    return d, c


def replicate_means(
    sums: NDArray[np.float64],
    counts: NDArray[np.float64],
    n_resamples: int,
    rng: np.random.Generator,
    max_elements: int,
) -> NDArray[np.float64]:
    """Bootstrap means of k cluster draws; indices are drawn chunk by chunk from the same stream."""
    k = sums.size
    check_int("max_elements", max_elements, 1)
    check_instance("rng", rng, np.random.Generator)
    if n_resamples * k > MAX_DRAWS:
        fail(f"n_resamples * n_clusters = {n_resamples * k} exceeds {MAX_DRAWS}")
    rows_per_chunk = max(1, max_elements // k)
    boot = np.empty(n_resamples, dtype=np.float64)
    done = 0
    while done < n_resamples:
        rows = min(rows_per_chunk, n_resamples - done)
        idx = rng.integers(0, k, size=(rows, k))
        boot[done : done + rows] = sums[idx].sum(axis=1) / counts[idx].sum(axis=1)
        done += rows
    return boot
