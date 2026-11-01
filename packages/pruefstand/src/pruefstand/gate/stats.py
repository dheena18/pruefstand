"""Statistical primitives of the gate (SPEC §7.2, ADR-0007): pure numbers in, numbers out.

The paired cluster bootstrap answers "did the candidate get worse?" for one metric on one slice.
Cases from one source document are not independent, so whole documents (clusters) are resampled
together; the estimand is still the mean over cases (every case has weight 1). The helpers around it
are an exact sign test for sparse data, the Wilson interval, and closed-form power and minimum
detectable effect. Nothing here does I/O, reads a clock or touches global random state.
"""

import math
from typing import Literal

import numpy as np
from numpy.typing import NDArray

from pruefstand.core.models.gate import BootstrapResult
from pruefstand.gate._resample import (
    MAX_INDEX_ELEMENTS,
    replicate_means,
    small_sample_factor,
    validate_bootstrap,
)
from pruefstand.gate._validate import (
    NORMAL,
    as_float_vector,
    check_finite,
    check_int,
    check_nonneg,
    check_open_unit,
    check_positive,
    fail,
    z_upper,
)

_EXACT_SIGN_TEST_MAX = 1000  # above this the binomial cdf comes from scipy.stats.binom
_SIGN_TEST_MIN_CLUSTERS = 10  # fewer non-zero cluster diffs than this -> exact sign test
_ZERO_TOL = 1e-12  # relative to the largest |diff|: a cluster mean this small counts as exactly 0


def sign_test_p(cluster_diffs: NDArray[np.float64]) -> float:
    """Exact one-sided sign test of "no drop" on cluster mean differences (negative = worse).

    Zeros are dropped. With m non-zero values of which ``n_pos`` are positive, the p-value is
    ``P(X <= n_pos)`` for ``X ~ Binomial(m, 0.5)``: few positives means a drop. m = 0 gives 1.0.

    Args:
        cluster_diffs: One mean difference per cluster.

    Returns:
        The one-sided p-value in [0, 1].

    Raises:
        GateInputError: Not one-dimensional, or NaN/infinite values.

    Examples:
        >>> sign_test_p(np.array([-1.0] * 6))  # all six clusters worse: 0.5**6
        0.015625
        >>> sign_test_p(np.array([-1.0, 1.0]))
        0.75
    """
    arr = as_float_vector("cluster_diffs", cluster_diffs)
    nonzero = arr[arr != 0.0]
    m = int(nonzero.size)
    if m == 0:
        return 1.0
    n_pos = int((nonzero > 0).sum())
    if m <= _EXACT_SIGN_TEST_MAX:
        return sum(math.comb(m, i) for i in range(n_pos + 1)) / (1 << m)  # exact integers
    from scipy.stats import binom  # noqa: PLC0415  (lazy: scipy is slow to import)

    return float(min(1.0, max(0.0, binom.cdf(n_pos, m, 0.5))))


def _cluster_sums(
    d: NDArray[np.float64], inverse: NDArray[np.intp], k: int
) -> tuple[NDArray[np.float64], NDArray[np.float64], float]:
    """Return per-cluster sums, per-cluster case counts and the case mean; fail on overflow."""
    counts = np.bincount(inverse, minlength=k).astype(np.float64)
    with np.errstate(over="ignore", invalid="ignore"):  # overflow is reported below as an error
        sums = np.bincount(inverse, weights=d, minlength=k)
        mean = float(d.mean())
    if not (np.isfinite(sums).all() and math.isfinite(mean)):
        fail("diffs overflow float64 when summed")
    return sums, counts, mean


def _p_value(
    cluster_means: NDArray[np.float64], scale: float, boot_c: NDArray[np.float64]
) -> tuple[Literal["bootstrap", "sign_test"], float]:
    """Pick the p-value: exact sign test below 10 non-zero cluster means, else the bootstrap p."""
    nonzero = cluster_means[np.abs(cluster_means) > _ZERO_TOL * max(scale, 1e-300)]
    if nonzero.size < _SIGN_TEST_MIN_CLUSTERS:
        return "sign_test", sign_test_p(nonzero)
    return "bootstrap", (1 + int((boot_c >= 0.0).sum())) / (boot_c.size + 1)


def paired_cluster_bootstrap(
    diffs: NDArray[np.float64],
    clusters: NDArray[np.str_],
    *,
    n_resamples: int,
    confidence: float,
    rng: np.random.Generator,
    alpha: float = 0.025,
    _max_index_elements: int = MAX_INDEX_ELEMENTS,
) -> BootstrapResult:
    """Paired cluster bootstrap of the mean difference with a one-sided p-value for "no drop".

    ``diffs[i]`` is candidate minus baseline for case i (negative = worse); cases with the same
    cluster id (one source document) are resampled together, k = number of distinct clusters. Each
    of B replicates draws k clusters with replacement and takes the mean over all their cases (the
    estimand is the case mean; clusters are only the resampling unit). Replicate deviations from
    the observed mean are multiplied by ``c_k = sqrt(k/(k-1)) * t(k-1, 1-alpha) / z(1-alpha)``
    (k >= 2) because the plain percentile bootstrap is anti-conservative for small k. Then
    ``p = (1 + #{replicate >= 0}) / (B + 1)``, the CI is the two-sided percentile interval at
    ``confidence`` (display only), ``se`` the standard deviation of the corrected replicates. With
    fewer than 10 clusters of non-zero mean difference, ``p`` is the exact sign-test p of those
    cluster means (``method="sign_test"``); CI and ``se`` stay bootstrap-based.

    Args:
        diffs: Per-case differences, negative = candidate worse; finite.
        clusters: Cluster id per case (non-empty strings), same length as ``diffs``.
        n_resamples: Number of replicates B, 1 to 10 000 000.
        confidence: Display CI level in (0, 1).
        rng: Source of randomness (the only one used).
        alpha: One-sided level of the decision rule, in (0, 0.5); enters ``c_k``.
        _max_index_elements: Chunk bound of the index array (test hook; result is independent).

    Returns:
        The ``BootstrapResult``.

    Raises:
        GateInputError: Mismatched, empty, non-numeric or non-finite input, a parameter out of
            range, or sums that overflow float64.

    Examples:
        SPEC §7.2: 40 clusters, each -0.06; every replicate is -0.06, so p = 1 / 10 001.
        >>> ids = np.array([f"d{i}" for i in range(40)])
        >>> r = paired_cluster_bootstrap(np.full(40, -0.06), ids, n_resamples=10_000,
        ...                              confidence=0.95, rng=np.random.default_rng(1))
        >>> round(r.mean_diff, 4), r.n_clusters, r.method, round(r.p_value, 6)
        (-0.06, 40, 'bootstrap', 0.0001)
    """
    d, c = validate_bootstrap(diffs, clusters, n_resamples, confidence, alpha)
    uniq, inverse = np.unique(c, return_inverse=True)
    k = int(uniq.size)
    sums, counts, mean = _cluster_sums(d, inverse, k)
    boot = replicate_means(sums, counts, n_resamples, rng, _max_index_elements)
    boot_c = mean + (boot - mean) * small_sample_factor(k, alpha)
    method, p = _p_value(sums / counts, float(np.abs(d).max()), boot_c)
    lo, hi = np.quantile(boot_c, [(1 - confidence) / 2, (1 + confidence) / 2])
    se = float(boot_c.std(ddof=1)) if n_resamples > 1 else 0.0
    return BootstrapResult(
        mean_diff=mean, ci_low=float(lo), ci_high=float(hi), p_value=p, method=method, se=se,
        n_cases=int(d.size), n_clusters=k, n_resamples=n_resamples, confidence=confidence,
    )  # fmt: skip


def wilson_interval(k: int, n: int, confidence: float = 0.95) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion k/n.

    Args:
        k: Events, 0 <= k <= n.
        n: Trials; ``n = 0`` returns the uninformative ``(0.0, 1.0)``.
        confidence: Two-sided level in (0, 1).

    Returns:
        ``(lower, upper)`` within [0, 1].

    Raises:
        GateInputError: ``k``/``n`` not integers with 0 <= k <= n, or ``confidence`` out of range.

    Examples:
        No event in 30 cases still leaves up to about 11 % possible:

        >>> lo, hi = wilson_interval(0, 30)
        >>> lo, round(hi, 4)
        (0.0, 0.1135)
    """
    n = check_int("n", n, 0)
    k = check_int("k", k, 0)
    if k > n:
        fail(f"k={k} exceeds n={n}")
    z = z_upper((1.0 - check_open_unit("confidence", confidence)) / 2.0)
    if n == 0:
        return 0.0, 1.0
    p = k / n
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    lower = 0.0 if k == 0 else max(0.0, centre - half)
    upper = 1.0 if k == n else min(1.0, centre + half)
    return lower, upper


def power_estimate(
    sigma_d: float,
    n_clusters: int,
    delta: float,
    alpha: float,
    m: int = 1,
    *,
    true_drop: float | None = None,
) -> float:
    """Normal approximation of P(FAIL) for one case per cluster.

    FAIL needs the mean below ``-max(delta, z * se)`` with ``z = z_(1-alpha/m)`` and
    ``se = sigma_d / sqrt(n_clusters)``, so the power is
    ``Phi((true_drop - max(delta, z*se)) / se)``.

    Args:
        sigma_d: Standard deviation of one per-cluster difference, > 0.
        n_clusters: Number of clusters, >= 1.
        delta: Relevance threshold ``max_drop`` (>= 0).
        alpha: One-sided level in (0, 1).
        m: Size of the Holm family (>= 1); the first Holm step tests at ``alpha / m``.
        true_drop: True size of the drop (positive = worse); defaults to ``2 * delta``.

    Returns:
        Probability in [0, 1].

    Raises:
        GateInputError: A parameter is non-finite or out of range.

    Examples:
        300 clusters, sigma 0.25, delta 0.03, true drop 0.06: se = 0.0144, so a 2-delta drop fails
        in about 98 % of runs.

        >>> round(power_estimate(0.25, 300, 0.03, 0.025), 3)
        0.981
    """
    sigma = check_positive("sigma_d", sigma_d)
    n = check_int("n_clusters", n_clusters, 1)
    delta = check_nonneg("delta", delta)
    z = z_upper(check_open_unit("alpha", alpha) / check_int("m", m, 1))
    drop = 2 * delta if true_drop is None else check_finite("true_drop", true_drop)
    se = sigma / math.sqrt(n)
    return NORMAL.cdf((drop - max(delta, z * se)) / se)


def minimum_detectable_effect(
    se: float, alpha: float, delta: float, power: float = 0.8, m: int = 1
) -> float:
    """Smallest true drop that the FAIL rule detects with probability ``power``.

    ``max((z_(1-alpha/m) + z_power) * se, delta + z_power * se)``: the first term is what
    significance needs, the second what relevance (``delta``) needs; the larger one binds.

    Args:
        se: Standard error of the mean difference (>= 0).
        alpha: One-sided level in (0, 1).
        delta: Relevance threshold ``max_drop`` (>= 0).
        power: Target power in (0, 1).
        m: Size of the Holm family (>= 1).

    Returns:
        The minimum detectable drop (>= 0).

    Raises:
        GateInputError: A parameter is non-finite or out of range.

    Examples:
        With se = 0.0144 the relevance term binds: 0.03 + 0.8416 * 0.0144.

        >>> round(minimum_detectable_effect(0.0144, 0.025, 0.03), 5)
        0.04212
    """
    se = check_nonneg("se", se)
    delta = check_nonneg("delta", delta)
    z_alpha = z_upper(check_open_unit("alpha", alpha) / check_int("m", m, 1))
    z_power = NORMAL.inv_cdf(check_open_unit("power", power))
    return max((z_alpha + z_power) * se, delta + z_power * se)
