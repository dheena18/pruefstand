"""paired_cluster_bootstrap: cases (a)-(j) of T1.6 plus hostile inputs."""

import math

import numpy as np
import pytest

from pruefstand.core.errors import GateInputError, PruefstandError
from pruefstand.core.models.gate import BootstrapResult
from pruefstand.gate._resample import small_sample_factor as _small_sample_factor
from pruefstand.gate.stats import paired_cluster_bootstrap


def _boot(
    diffs: np.ndarray,
    clusters: np.ndarray,
    *,
    seed: int = 1,
    b: int = 2000,
    **kw: object,
) -> BootstrapResult:
    return paired_cluster_bootstrap(
        diffs,
        clusters,
        n_resamples=b,
        confidence=0.95,
        rng=np.random.default_rng(seed),
        **kw,  # type: ignore[arg-type]  # forwarded test kwargs
    )


def _ids(n: int) -> np.ndarray:
    return np.array([f"d{i}" for i in range(n)])


def test_a_constant_drop() -> None:
    r = _boot(np.full(40, -0.06), _ids(40))
    assert r.mean_diff == pytest.approx(-0.06)
    assert r.ci_low == pytest.approx(-0.06, abs=1e-12)
    assert r.ci_high == pytest.approx(-0.06, abs=1e-12)
    assert r.se == pytest.approx(0.0, abs=1e-12)
    assert r.p_value == pytest.approx(1 / 2001)
    assert r.method == "bootstrap"
    assert (r.n_cases, r.n_clusters, r.n_resamples, r.confidence) == (40, 40, 2000, 0.95)


def test_b_all_zero() -> None:
    r = _boot(np.zeros(40), _ids(40))
    assert r.p_value == 1.0
    assert (r.ci_low, r.ci_high) == (0.0, 0.0)


def test_c_positive_effect_not_significant() -> None:
    d = np.random.default_rng(3).normal(0.05, 0.1, 40)
    assert _boot(d, _ids(40)).p_value > 0.5


def test_d_deterministic() -> None:
    d = np.random.default_rng(4).normal(-0.02, 0.1, 60)
    c = np.array([f"d{i // 2}" for i in range(60)])
    assert _boot(d, c, seed=9) == _boot(d, c, seed=9)


def test_e_chunk_invariance() -> None:
    d = np.random.default_rng(5).normal(-0.02, 0.1, 61)
    c = np.array([f"d{i // 2}" for i in range(61)])
    ref = _boot(d, c, seed=11, b=777)
    for chunk in (31, 100, 5000):
        assert _boot(d, c, seed=11, b=777, _max_index_elements=chunk) == ref


def test_f_n_clusters_counts_distinct() -> None:
    d = np.random.default_rng(6).normal(0, 0.1, 30)
    c = np.array([f"d{i % 7}" for i in range(30)])
    r = _boot(d, c)
    assert (r.n_cases, r.n_clusters) == (30, 7)


@pytest.mark.parametrize("bad", [np.nan, np.inf, -np.inf])
def test_g_non_finite_rejected(bad: float) -> None:
    d = np.zeros(10)
    d[3] = bad
    with pytest.raises(GateInputError):
        _boot(d, _ids(10))


def test_h_cluster_effect_widens_ci() -> None:
    vals = np.random.default_rng(7).normal(0, 0.1, 10)
    clustered = _boot(np.repeat(vals, 10), np.repeat(_ids(10), 10))
    singletons = _boot(np.repeat(vals, 10), _ids(100))
    assert clustered.ci_high - clustered.ci_low > 2 * (singletons.ci_high - singletons.ci_low)


def test_i_sign_test_fallback() -> None:
    d = np.zeros(40)
    d[:6] = -1.0
    r = _boot(d, _ids(40))
    assert r.method == "sign_test"
    assert r.p_value == pytest.approx(0.5**6)
    assert r.ci_low <= r.mean_diff <= r.ci_high


def test_i2_bootstrap_when_ten_nonzero_clusters() -> None:
    d = np.zeros(40)
    d[:10] = -1.0
    assert _boot(d, _ids(40)).method == "bootstrap"


def test_j_correction_factor() -> None:
    assert _small_sample_factor(30, 0.025) == pytest.approx(1.0613, abs=1e-3)
    assert _small_sample_factor(300, 0.025) == pytest.approx(1.0058, abs=1e-3)
    assert _small_sample_factor(1, 0.025) == 1.0
    assert _small_sample_factor(2, 0.025) > _small_sample_factor(3, 0.025) > 1.0


def test_correction_widens_ci_vs_plain() -> None:
    d = np.random.default_rng(8).normal(-0.05, 0.2, 30)
    r = _boot(d, _ids(30), b=4000)
    # uncorrected percentile SE is about sd/sqrt(30); the corrected SE is larger by c_30
    plain_se = d.std(ddof=0) / math.sqrt(30)
    assert r.se == pytest.approx(plain_se * _small_sample_factor(30, 0.025), rel=0.1)


def test_single_cluster_is_degenerate_but_valid() -> None:
    r = _boot(np.array([-0.1, -0.3]), np.array(["x", "x"]))
    assert r.n_clusters == 1
    assert r.method == "sign_test"
    assert r.mean_diff == pytest.approx(-0.2)
    assert r.se == pytest.approx(0.0, abs=1e-12)
    assert r.p_value == pytest.approx(1 / 2)  # one negative cluster: P(X <= 0 | m=1)


def test_single_case() -> None:
    r = _boot(np.array([0.5]), np.array(["x"]), b=10)
    assert r.p_value == 1.0
    assert r.n_cases == 1


def test_unequal_cluster_sizes_estimand_is_case_mean() -> None:
    d = np.array([-1.0] * 9 + [0.0])
    c = np.array(["big"] * 9 + ["small"])
    assert _boot(d, c).mean_diff == pytest.approx(-0.9)


def test_alpha_changes_result() -> None:
    d = np.random.default_rng(10).normal(-0.05, 0.2, 30)
    assert _boot(d, _ids(30), alpha=0.05).se != _boot(d, _ids(30), alpha=0.025).se


@pytest.mark.parametrize(
    "kwargs",
    [
        {"n_resamples": 0},
        {"n_resamples": -5},
        {"n_resamples": 10_000_001},
        {"n_resamples": True},
        {"n_resamples": 10.0},
        {"confidence": 0.0},
        {"confidence": 1.0},
        {"confidence": float("nan")},
        {"alpha": 0.0},
        {"alpha": 0.5},
        {"alpha": float("nan")},
    ],
)
def test_invalid_parameters(kwargs: dict[str, object]) -> None:
    base: dict[str, object] = {"n_resamples": 10, "confidence": 0.95}
    base.update(kwargs)
    with pytest.raises(GateInputError):
        paired_cluster_bootstrap(
            np.zeros(5),
            _ids(5),
            rng=np.random.default_rng(0),
            **base,  # type: ignore[arg-type]  # parametrised
        )


def test_invalid_shapes() -> None:
    with pytest.raises(GateInputError):
        _boot(np.zeros(5), _ids(4))
    with pytest.raises(GateInputError):
        _boot(np.array([]), np.array([], dtype=str))
    with pytest.raises(GateInputError):
        _boot(np.zeros((2, 2)), _ids(4))
    with pytest.raises(GateInputError):
        _boot(np.zeros(3), np.zeros(3))  # clusters must be strings
    with pytest.raises(GateInputError):
        _boot(np.zeros(3), np.array(["a", "", "b"]))  # empty cluster id


def test_overflow_is_an_error_not_nan() -> None:
    with pytest.raises(PruefstandError):
        _boot(np.array([1.7e308, 1.7e308, 1.7e308]), _ids(3))


def test_bad_chunk_parameter() -> None:
    with pytest.raises(GateInputError):
        _boot(np.zeros(5), _ids(5), _max_index_elements=0)


def test_input_not_mutated() -> None:
    d = np.random.default_rng(12).normal(0, 0.1, 20)
    before = d.copy()
    _boot(d, _ids(20))
    assert np.array_equal(d, before)


def test_non_numeric_diffs_rejected() -> None:
    with pytest.raises(GateInputError):
        _boot(np.array(["a", "b"]), np.array(["x", "y"]))


def test_huge_resamples_rejected_before_any_work() -> None:
    with pytest.raises(GateInputError):
        _boot(np.zeros(5), _ids(5), b=10**12)


def test_total_work_is_bounded() -> None:
    with pytest.raises(GateInputError, match="exceeds"):
        _boot(np.zeros(2000), _ids(2000), b=10_000_000)
