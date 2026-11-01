"""Argument checks shared by the gate modules: every bad input raises ``GateInputError``."""

import math
from statistics import NormalDist, StatisticsError
from typing import NoReturn

import numpy as np
from numpy.typing import NDArray

from pruefstand.core.errors import GateInputError

NORMAL = NormalDist()


def fail(message: str) -> NoReturn:
    """Raise ``GateInputError(message)``; the one place that builds this error.

    Raises:
        GateInputError: Always.
    """
    raise GateInputError(message)


def z_upper(tail: float) -> float:
    """Return z with P(Z > z) = ``tail``, computed from the lower tail to keep tiny tails exact."""
    try:
        return -NORMAL.inv_cdf(tail)
    except StatisticsError as exc:
        msg = f"tail probability {tail!r} is outside the open interval (0, 1)"
        raise GateInputError(msg) from exc


def _number(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float | np.integer | np.floating):
        fail(f"{name} must be a number, got {value!r}")
    return float(value)


def check_instance(name: str, value: object, cls: type) -> None:
    """Fail unless ``value`` is an instance of ``cls``."""
    if not isinstance(value, cls):
        fail(f"{name} must be a {cls.__module__}.{cls.__qualname__}, got {type(value).__name__}")


def check_int(name: str, value: object, low: int) -> int:
    """Return ``value`` as ``int`` if it is an integer (not bool) >= ``low``, else fail."""
    if isinstance(value, bool) or not isinstance(value, int | np.integer) or value < low:
        fail(f"{name} must be an integer >= {low}, got {value!r}")
    return int(value)


def check_open_unit(name: str, value: object, high: float = 1.0) -> float:
    """Return ``value`` as ``float`` if it lies in the open interval (0, high), else fail."""
    v = _number(name, value)
    if not 0.0 < v < high:
        fail(f"{name} must lie in (0, {high}), got {value!r}")
    return v


def check_nonneg(name: str, value: object) -> float:
    """Return ``value`` as ``float`` if it is finite and >= 0, else fail."""
    v = _number(name, value)
    if not math.isfinite(v) or v < 0:
        fail(f"{name} must be finite and >= 0, got {value!r}")
    return v


def check_positive(name: str, value: object) -> float:
    """Return ``value`` as ``float`` if it is finite and > 0, else fail."""
    v = _number(name, value)
    if not math.isfinite(v) or v <= 0:
        fail(f"{name} must be finite and > 0, got {value!r}")
    return v


def check_finite(name: str, value: object) -> float:
    """Return ``value`` as ``float`` if it is finite, else fail."""
    v = _number(name, value)
    if not math.isfinite(v):
        fail(f"{name} must be finite, got {value!r}")
    return v


def as_float_vector(name: str, values: object) -> NDArray[np.float64]:
    try:
        arr = np.asarray(values, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        msg = f"{name} must be numeric"
        raise GateInputError(msg) from exc
    if arr.ndim != 1:
        fail(f"{name} must be one-dimensional")
    if not np.isfinite(arr).all():
        fail(f"{name} contains NaN or infinite values")
    return arr
