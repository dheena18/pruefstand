"""Holm and Benjamini-Hochberg adjustment (worked vectors from T1.6)."""

import pytest

from pruefstand.core.errors import GateInputError
from pruefstand.gate.correction import bh_adjust, holm_adjust

P = [0.01, 0.04, 0.03, 0.005]


def test_holm_worked() -> None:
    assert holm_adjust(P) == pytest.approx([0.03, 0.06, 0.06, 0.02])


def test_bh_worked() -> None:
    assert bh_adjust(P) == pytest.approx([0.02, 0.04, 0.04, 0.02])


def test_holm_clipped() -> None:
    assert holm_adjust([0.6, 0.9]) == [1.0, 1.0]


def test_bh_clipped() -> None:
    assert bh_adjust([0.9, 0.95]) == pytest.approx([0.95, 0.95])


def test_empty() -> None:
    assert holm_adjust([]) == []
    assert bh_adjust([]) == []


def test_single() -> None:
    assert holm_adjust([0.04]) == [0.04]
    assert bh_adjust([0.04]) == [0.04]


def test_ties_keep_order() -> None:
    assert holm_adjust([0.01, 0.01, 0.5]) == pytest.approx([0.03, 0.03, 0.5])


@pytest.mark.parametrize("bad", [[float("nan")], [-0.1], [1.1], [float("inf"), 0.5]])
@pytest.mark.parametrize("fn", [holm_adjust, bh_adjust])
def test_rejects_invalid(fn: object, bad: list[float]) -> None:
    with pytest.raises(GateInputError):
        fn(bad)  # type: ignore[operator]  # parametrised callable
