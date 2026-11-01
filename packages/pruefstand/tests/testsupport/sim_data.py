"""Simulated paired differences with a known true effect (testing-strategy §3.4).

The numbers are simulated because the ground truth (true delta) must be known; this validates the
maths of ``pruefstand.gate``, it is not a stand-in for the product.
"""

from collections.abc import Sequence
from typing import Literal

import numpy as np
from numpy.typing import NDArray


def simulate_paired(  # noqa: PLR0913  (test helper fixed by testing-strategy §3.4 + n_sims)
    n_clusters: int,
    cluster_size: int,
    true_delta: float,
    *,
    sigma_d: float,
    icc: float,
    kind: Literal["gaussian", "binary"],
    discordance: float,
    rng: np.random.Generator,
    cluster_sizes: Sequence[int] | None = None,
    n_sims: int = 1,
) -> tuple[NDArray[np.float64], NDArray[np.str_]]:
    """Draw ``n_sims`` independent paired-difference vectors sharing one cluster layout.

    Gaussian: cluster effect variance ``icc * sigma_d**2``, case noise variance
    ``(1 - icc) * sigma_d**2``, mean ``true_delta``. Binary: each case difference is -1, 0 or +1
    with P(!= 0) = ``discordance`` and P(+1 | != 0) = 0.5 + ``true_delta`` / (2 * discordance),
    clipped to [0, 1]; ``sigma_d`` and ``icc`` are ignored.

    Args:
        n_clusters: Number of clusters (ignored when ``cluster_sizes`` is given).
        cluster_size: Cases per cluster (ignored when ``cluster_sizes`` is given).
        true_delta: True mean difference (negative = candidate worse).
        sigma_d: Standard deviation of one case difference (Gaussian only).
        icc: Intra-cluster correlation in [0, 1) (Gaussian only).
        kind: ``"gaussian"`` or ``"binary"``.
        discordance: P(difference != 0) for ``kind="binary"``.
        rng: Source of randomness.
        cluster_sizes: One size per cluster; overrides ``n_clusters`` and ``cluster_size``.
        n_sims: Number of simulations drawn at once.

    Returns:
        ``(diffs, clusters)``: ``diffs`` has shape ``(n_sims, n_cases)``; ``clusters`` has shape
        ``(n_cases,)`` and is the same for every simulation.

    Raises:
        ValueError: A parameter is out of range.
    """
    sizes = np.asarray(
        cluster_sizes if cluster_sizes is not None else [cluster_size] * n_clusters, dtype=np.int64
    )
    if sizes.size == 0 or (sizes < 1).any() or n_sims < 1:
        msg = "need at least one cluster of at least one case and n_sims >= 1"
        raise ValueError(msg)
    k = sizes.size
    n_cases = int(sizes.sum())
    clusters = np.repeat(np.array([f"d{i}" for i in range(k)]), sizes)
    owner = np.repeat(np.arange(k), sizes)
    if kind == "gaussian":
        if not 0.0 <= icc < 1.0 or sigma_d < 0:
            msg = "icc must be in [0, 1) and sigma_d >= 0"
            raise ValueError(msg)
        effect = rng.normal(0.0, sigma_d * np.sqrt(icc), size=(n_sims, k))
        noise = rng.normal(0.0, sigma_d * np.sqrt(1.0 - icc), size=(n_sims, n_cases))
        return true_delta + effect[:, owner] + noise, clusters
    if not 0.0 < discordance <= 1.0:
        msg = "discordance must be in (0, 1]"
        raise ValueError(msg)
    p_plus = float(np.clip(0.5 + true_delta / (2.0 * discordance), 0.0, 1.0))
    nonzero = rng.random((n_sims, n_cases)) < discordance
    plus = rng.random((n_sims, n_cases)) < p_plus
    return np.where(nonzero, np.where(plus, 1.0, -1.0), 0.0), clusters
