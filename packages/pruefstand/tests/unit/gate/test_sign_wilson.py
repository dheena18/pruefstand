"""sign_test_p and wilson_interval (T1.6 worked values)."""

import numpy as np
import pytest

from pruefstand.core.errors import GateInputError
from pruefstand.gate.stats import sign_test_p, wilson_interval


def test_sign_test_six_negatives() -> None:
    assert sign_test_p(np.array([-1.0] * 6)) == pytest.approx(0.015625)


def test_sign_test_one_each() -> None:
    assert sign_test_p(np.array([-1.0, 1.0])) == pytest.approx(0.75)


def test_sign_test_empty_and_all_zero() -> None:
    assert sign_test_p(np.array([])) == 1.0
    assert sign_test_p(np.zeros(5)) == 1.0


def test_sign_test_all_positive() -> None:
    assert sign_test_p(np.array([1.0, 1.0])) == 1.0


def test_sign_test_ignores_zeros() -> None:
    assert sign_test_p(np.array([-1.0, 0.0, -1.0, 0.0])) == pytest.approx(0.25)


@pytest.mark.parametrize("bad", [np.array([np.nan]), np.array([np.inf, 1.0]), np.zeros((2, 2))])
def test_sign_test_rejects_invalid(bad: np.ndarray) -> None:
    with pytest.raises(GateInputError):
        sign_test_p(bad)


def test_wilson_zero_of_thirty() -> None:
    lo, hi = wilson_interval(0, 30)
    assert lo == 0.0
    assert hi == pytest.approx(0.1135, abs=1e-3)


def test_wilson_thirty_of_thirty() -> None:
    lo, hi = wilson_interval(30, 30)
    assert lo == pytest.approx(0.8865, abs=1e-3)
    assert hi == 1.0


def test_wilson_one_of_fifty() -> None:
    assert wilson_interval(1, 50)[0] == pytest.approx(0.0035, abs=1e-3)


def test_wilson_empty() -> None:
    assert wilson_interval(0, 0) == (0.0, 1.0)


def test_wilson_confidence_widens() -> None:
    lo95, hi95 = wilson_interval(10, 100, 0.95)
    lo99, hi99 = wilson_interval(10, 100, 0.99)
    assert lo99 < lo95 < hi95 < hi99


@pytest.mark.parametrize(
    ("k", "n", "conf"),
    [(-1, 10, 0.95), (11, 10, 0.95), (1, -1, 0.95), (1, 10, 0.0), (1, 10, 1.0), (1, 10, float("nan"))],
)
def test_wilson_rejects_invalid(k: int, n: int, conf: float) -> None:
    with pytest.raises(GateInputError):
        wilson_interval(k, n, conf)


def test_wilson_rejects_non_int() -> None:
    with pytest.raises(GateInputError):
        wilson_interval(1.5, 10)  # type: ignore[arg-type]  # deliberately wrong type
