"""T6.3 S2b (core): mean-zero A/A pairs at the bounds, the production gate, alarm counting."""

import numpy as np
import pytest
from noise.replay import aa_pair, counts, replay, split_shift
from testsupport.builders import fixture_f0, make_run
from testsupport.gate_helpers import DIRECTIONS, POLICY

from pruefstand.core.enums import GateStatus
from pruefstand.core.models.run import RunResults


def baseline(value: float | None = None, *, latency: bool = False) -> RunResults:
    cases, values = fixture_f0()
    if value is not None:
        values = {**values, "context_recall": [value] * len(cases)}
    if latency:
        values = {**values, "latency_ms": [0.8] * len(cases)}  # the builder keeps values in [0, 1]
    return make_run("base", cases, values)


def mean_diff(run: RunResults, sigma: float, pairs: int) -> float:
    rng = np.random.default_rng(5)
    total, n = 0.0, 0
    for _ in range(pairs):
        left, right = aa_pair(run, {"context_recall": sigma}, rng)
        for lc, rc in zip(left.values, right.values, strict=True):
            lv = next(v.value for v in lc.values if v.metric == "context_recall")
            rv = next(v.value for v in rc.values if v.metric == "context_recall")
            assert lv is not None
            assert rv is not None
            assert 0.0 <= lv <= 1.0
            assert 0.0 <= rv <= 1.0
            total, n = total + rv - lv, n + 1
    return total / n


@pytest.mark.parametrize(("value", "sigma"), [(0.8, 0.25), (1.0, 0.10), (1.0, 0.25)])
def test_the_pair_is_mean_zero_even_at_the_bounds(value: float, sigma: float) -> None:
    # a plain clip of base + e gave -0.037 (0.8, 0.25) and 200/200 FAIL (1.0, 0.25)
    assert abs(mean_diff(baseline(value), sigma, 200)) < 0.01


@pytest.mark.parametrize(("value", "sigma"), [(0.8, 0.25), (1.0, 0.10), (1.0, 0.25)])
def test_the_production_gate_does_not_fail_an_a_a_pair(value: float, sigma: float) -> None:
    result = replay(
        baseline(value), {"context_recall": sigma}, POLICY, directions=DIRECTIONS, n=4, seed=11
    )
    assert result.fail == 0


@pytest.mark.parametrize(
    ("base", "shift"), [(0.5, 0.2), (1.0, 0.3), (0.0, -0.3), (0.9, -1.0), (0.2, 0.0)]
)
def test_split_shift_keeps_both_values_in_bounds_and_the_difference_exact(
    base: float, shift: float
) -> None:
    left, right = split_shift(base, shift)
    assert 0.0 <= left <= 1.0
    assert 0.0 <= right <= 1.0
    assert right - left == pytest.approx(shift)


def test_latency_and_metrics_without_sigma_are_never_shifted() -> None:
    left, right = aa_pair(
        baseline(latency=True),
        {"context_recall": 0.2, "latency_ms": 50.0},
        np.random.default_rng(3),
    )
    for lc, rc in zip(left.values, right.values, strict=True):
        lv = {v.metric: v.value for v in lc.values}
        rv = {v.metric: v.value for v in rc.values}
        assert lv["latency_ms"] == rv["latency_ms"] == 0.8
        assert lv["faithfulness"] == rv["faithfulness"]


def test_one_shift_per_cluster() -> None:
    left, right = aa_pair(baseline(0.5), {"context_recall": 0.2}, np.random.default_rng(4))
    shifts: dict[str, set[float]] = {}
    for lc, rc in zip(left.values, right.values, strict=True):
        lv = next(v.value for v in lc.values if v.metric == "context_recall")
        rv = next(v.value for v in rc.values if v.metric == "context_recall")
        assert lv is not None
        assert rv is not None
        shifts.setdefault(lc.case.cluster_id, set()).add(round(rv - lv, 9))
    assert all(len(s) == 1 for s in shifts.values())


def test_counting_unsupported_is_a_warn_and_insufficient_is_neither() -> None:
    statuses = [GateStatus.FAIL, GateStatus.WARN, GateStatus.UNSUPPORTED_CONFIG,
                GateStatus.INSUFFICIENT_DATA, GateStatus.PASS]  # fmt: skip
    assert counts(statuses) == (5, 1, 3)


def test_the_seed_fixes_the_counts() -> None:
    sigma = {"context_recall": 0.3}
    first = replay(baseline(), sigma, POLICY, directions=DIRECTIONS, n=2, seed=7)
    assert first == replay(baseline(), sigma, POLICY, directions=DIRECTIONS, n=2, seed=7)
