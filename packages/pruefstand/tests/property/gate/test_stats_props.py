"""Hypothesis properties of the gate statistics (T1.6)."""

import numpy as np
from hypothesis import assume, given
from hypothesis import strategies as st

from pruefstand.gate.correction import bh_adjust, holm_adjust
from pruefstand.gate.stats import paired_cluster_bootstrap

_diff = st.floats(-1.0, 1.0, allow_nan=False, allow_infinity=False)
_diffs = st.lists(_diff, min_size=3, max_size=40)
_ps = st.lists(st.floats(0.0, 1.0, allow_nan=False), min_size=0, max_size=30)


def _run(diffs: list[float], n_clusters: int, shift: float = 0.0):
    d = np.array(diffs, dtype=np.float64) + shift
    clusters = np.array([f"d{i % n_clusters}" for i in range(len(d))])
    return paired_cluster_bootstrap(
        d, clusters, n_resamples=200, confidence=0.95, rng=np.random.default_rng(42)
    )


@given(_diffs, st.integers(2, 20))
def test_ci_contains_mean(diffs: list[float], k: int) -> None:
    r = _run(diffs, k)
    assert r.ci_low - 1e-9 <= r.mean_diff <= r.ci_high + 1e-9


@given(_diffs, st.integers(2, 20), st.floats(-0.5, 0.5))
def test_shift_equivariance(diffs: list[float], k: int, c: float) -> None:
    r0, r1 = _run(diffs, k), _run(diffs, k, c)
    assert abs(r1.mean_diff - (r0.mean_diff + c)) < 1e-9
    assert abs(r1.ci_low - (r0.ci_low + c)) < 1e-9
    assert abs(r1.ci_high - (r0.ci_high + c)) < 1e-9


@given(_diffs, st.integers(2, 20), st.floats(0.01, 0.5))
def test_p_non_increasing_when_diffs_drop(diffs: list[float], k: int, c: float) -> None:
    r0, r1 = _run(diffs, k), _run(diffs, k, -c)
    assume(r0.method == r1.method)  # the sign-test switch is a different p scale
    assert r1.p_value <= r0.p_value + 1e-12


@given(_ps)
def test_holm_properties(ps: list[float]) -> None:
    adj = holm_adjust(ps)
    assert len(adj) == len(ps)
    assert all(a >= p - 1e-12 and a <= 1.0 for a, p in zip(adj, ps, strict=True))
    by_raw = [a for _, a in sorted(zip(ps, adj, strict=True), key=lambda t: t[0])]
    assert all(x <= y + 1e-12 for x, y in zip(by_raw, by_raw[1:], strict=False))


@given(_ps)
def test_bh_leq_holm(ps: list[float]) -> None:
    holm, bh = holm_adjust(ps), bh_adjust(ps)
    assert all(b <= h + 1e-12 for b, h in zip(bh, holm, strict=True))
    assert all(b >= p - 1e-12 for b, p in zip(bh, ps, strict=True))
