"""The CPU-time helpers of ``testsupport.timing`` (D840) detect what they claim to detect."""

import time
from collections.abc import Callable

import pytest
from testsupport import timing
from testsupport.timing import (
    assert_scales_linearly,
    cpu_budget,
    cpu_seconds,
    linear_ratio_limit,
)


def _spin(iterations: int) -> Callable[[], object]:
    def run() -> None:
        for _ in range(iterations):
            pass

    return run


def test_ratio_limit_sits_between_linear_and_quadratic() -> None:
    for scale in (2, 4, 8, 10):
        assert scale < linear_ratio_limit(scale) < scale**2


def test_linear_work_passes() -> None:
    assert_scales_linearly(_spin(20_000), _spin(80_000), scale=4, floor_s=1e-4)


def test_quadratic_work_fails_with_the_measured_ratio() -> None:
    quadratic_big = _spin(80_000 * 80_000 // 20_000)  # 16x the small cost for 4x the input
    with pytest.raises(AssertionError, match=r"4x input cost .*x \(limit 10\.0x\)"):
        assert_scales_linearly(_spin(20_000), quadratic_big, scale=4, floor_s=1e-4)


def test_an_explicit_limit_overrides_the_default() -> None:
    with pytest.raises(AssertionError, match=r"limit 1.5x"):
        assert_scales_linearly(_spin(20_000), _spin(80_000), scale=4, limit=1.5, floor_s=1e-4)


def test_hang_guard_fails_whatever_the_ratio(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(timing, "HANG_GUARD_S", 0.0)
    with pytest.raises(AssertionError, match="CPU s"):
        assert_scales_linearly(_spin(10), _spin(40), scale=4)


def test_cpu_seconds_ignores_waiting() -> None:
    assert cpu_seconds(lambda: time.sleep(0.05)) < 0.04
    assert cpu_seconds(_spin(200_000)) > 0.0


def test_cpu_budget_passes_inside_and_fails_outside_the_limit() -> None:
    with cpu_budget(5.0):
        _spin(1_000)()
    with pytest.raises(AssertionError, match=r"used .* CPU s \(limit 0 s\)"), cpu_budget(0.0):
        _spin(10_000)()
