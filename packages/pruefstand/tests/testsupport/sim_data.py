"""Simulated paired differences with a known true effect (testing-strategy §3.4).

The numbers are simulated because the ground truth (true delta) must be known; this validates the
maths of ``pruefstand.gate``, it is not a stand-in for the product.
"""

import functools
import math
from collections.abc import Sequence
from typing import Literal

import numpy as np
from numpy.typing import NDArray
from testsupport.builders import NA, make_case, make_run

from pruefstand.core.models.run import RunResults
from pruefstand.core.models.testcase import TestCase


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


# --- full-gate no-op generator (testing-strategy §3.4, T1.7) ----------------------------------

_NOOP_CLUSTERS = 150
_NOOP_TENANTS = ("kanzlei_mueller", "versicherung_nord", "stadtwerke_sued")
_CONTINUOUS = ("faithfulness", "answer_correctness")
_BINARY = (
    "context_recall", "ndcg_at_k", "citation_recall", "refusal_correct", "false_refusal",
    "language_match",
)  # fmt: skip
_PAIR_CUTS = (0.775, 0.95, 0.975)  # (1,1) 0.775, (0,0) 0.175, (1,0) 0.025, (0,1) 0.025
_INJECTION_CASES = 60  # clusters 0-29, both cases


@functools.cache
def _noop_cases() -> tuple[TestCase, ...]:
    return tuple(
        make_case(
            i,
            cluster=i // 2,
            tenant=_NOOP_TENANTS[i // 2 // 50],
            lang="de" if i // 2 < 125 else "en",
        )
        for i in range(2 * _NOOP_CLUSTERS)
    )


def simulate_noop_runs(rng: np.random.Generator) -> tuple[RunResults, RunResults]:
    """Return a baseline and a candidate run that differ by noise only (true change 0).

    150 clusters x 2 cases; tenants by cluster in thirds; ``lang`` ``de`` for clusters 0-124.
    ``faithfulness`` and ``answer_correctness``: baseline 0.5, candidate ``clip(0.5 + d)`` with
    ``d`` = cluster effect N(0, 0.3 * 0.2**2) + case noise N(0, 0.7 * 0.2**2). The binary metrics
    draw pair outcomes (1,1) 0.775, (0,0) 0.175, (1,0) 0.025, (0,1) 0.025 per case.
    ``injection_success`` is Bernoulli(0.01) in both runs on the 60 injection cases and
    ``not_applicable`` elsewhere; ``error_rate`` is 0.

    Args:
        rng: Source of randomness.

    Returns:
        ``(baseline, candidate)``.
    """
    cases = _noop_cases()
    n = len(cases)
    owner = np.repeat(np.arange(_NOOP_CLUSTERS), 2)
    base: dict[str, list[float | None]] = {}
    cand: dict[str, list[float | None]] = {}
    for metric in _CONTINUOUS:
        effect = rng.normal(0.0, math.sqrt(0.3) * 0.2, size=_NOOP_CLUSTERS)
        noise = rng.normal(0.0, math.sqrt(0.7) * 0.2, size=n)
        base[metric] = [0.5] * n
        cand[metric] = np.clip(0.5 + effect[owner] + noise, 0.0, 1.0).tolist()
    for metric in _BINARY:
        draw = np.searchsorted(_PAIR_CUTS, rng.random(n), side="right")
        base[metric] = np.isin(draw, (0, 2)).astype(float).tolist()
        cand[metric] = np.isin(draw, (0, 3)).astype(float).tolist()
    pad = [NA] * (n - _INJECTION_CASES)
    base["injection_success"] = [*(rng.random(_INJECTION_CASES) < 0.01).astype(float), *pad]
    cand["injection_success"] = [*(rng.random(_INJECTION_CASES) < 0.01).astype(float), *pad]
    base["error_rate"] = cand["error_rate"] = [0.0] * n
    for leak in ("canary_leak", "tenant_leak", "system_prompt_leak"):
        base[leak] = cand[leak] = [0.0] * n
    return make_run("base", cases, base), make_run("cand", cases, cand)
