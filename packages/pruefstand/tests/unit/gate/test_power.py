"""power_estimate and minimum_detectable_effect (T1.6 worked values)."""

import pytest

from pruefstand.core.errors import GateInputError
from pruefstand.gate.stats import minimum_detectable_effect, power_estimate


def test_power_default_true_drop() -> None:
    assert power_estimate(0.25, 300, 0.03, 0.025) == pytest.approx(0.981, abs=0.005)


def test_power_at_delta_is_half() -> None:
    assert power_estimate(0.25, 300, 0.03, 0.025, true_drop=0.03) == pytest.approx(0.5, abs=0.01)


def test_power_small_n_below_half() -> None:
    assert power_estimate(0.25, 50, 0.03, 0.025) < 0.5


def test_power_decreases_with_m() -> None:
    assert power_estimate(0.4, 100, 0.03, 0.025, m=40) < power_estimate(0.4, 100, 0.03, 0.025)


def test_mde_delta_binding() -> None:
    assert minimum_detectable_effect(0.0144, 0.025, 0.03) == pytest.approx(0.04212, abs=1e-4)


def test_mde_significance_binding() -> None:
    assert minimum_detectable_effect(0.05, 0.025, 0.03) == pytest.approx(0.14008, abs=1e-4)


def test_mde_grows_with_m() -> None:
    assert minimum_detectable_effect(0.05, 0.025, 0.03, m=40) > minimum_detectable_effect(
        0.05, 0.025, 0.03
    )


def test_mde_zero_se_is_delta() -> None:
    assert minimum_detectable_effect(0.0, 0.025, 0.03) == pytest.approx(0.03)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"sigma_d": 0.0, "n_clusters": 10, "delta": 0.03, "alpha": 0.025},
        {"sigma_d": float("nan"), "n_clusters": 10, "delta": 0.03, "alpha": 0.025},
        {"sigma_d": 0.2, "n_clusters": 0, "delta": 0.03, "alpha": 0.025},
        {"sigma_d": 0.2, "n_clusters": 10, "delta": -0.01, "alpha": 0.025},
        {"sigma_d": 0.2, "n_clusters": 10, "delta": 0.03, "alpha": 0.0},
        {"sigma_d": 0.2, "n_clusters": 10, "delta": 0.03, "alpha": 1.0},
        {"sigma_d": 0.2, "n_clusters": 10, "delta": 0.03, "alpha": 0.025, "m": 0},
        {
            "sigma_d": 0.2,
            "n_clusters": 10,
            "delta": 0.03,
            "alpha": 0.025,
            "true_drop": float("inf"),
        },
    ],
)
def test_power_rejects_invalid(kwargs: dict[str, float]) -> None:
    with pytest.raises(GateInputError):
        power_estimate(**kwargs)  # type: ignore[arg-type]  # parametrised kwargs


_MDE_OK = {"se": 0.01, "alpha": 0.025, "delta": 0.03}


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("se", -1.0),
        ("se", float("inf")),
        ("alpha", 0.0),
        ("delta", -1.0),
        ("power", 1.0),
        ("m", 0),
    ],
)
def test_mde_rejects_invalid(name: str, value: float) -> None:
    kwargs = {**_MDE_OK, name: value}
    with pytest.raises(GateInputError, match=name):
        minimum_detectable_effect(**kwargs)  # type: ignore[arg-type]  # parametrised kwargs


def test_power_tail_underflow_is_an_error() -> None:
    with pytest.raises(GateInputError):
        power_estimate(0.2, 10, 0.03, 1e-300, m=10**30)


@pytest.mark.parametrize("bad", ["0.2", None, True, [0.2]])
def test_power_rejects_non_numbers(bad: object) -> None:
    with pytest.raises(GateInputError):
        power_estimate(bad, 10, 0.03, 0.025)  # type: ignore[arg-type]  # deliberately wrong type


def test_power_single_cluster_is_valid() -> None:
    assert 0.0 <= power_estimate(0.2, 1, 0.03, 0.025) <= 1.0
