"""decide and decide_absolute (SPEC §7.2 decision rule)."""

import pytest

from pruefstand.core.enums import GateStatus
from pruefstand.core.errors import GateInputError
from pruefstand.core.models.gate import BootstrapResult
from pruefstand.gate.decision import decide, decide_absolute


def _r(mean_diff: float = -0.06, n_clusters: int = 300) -> BootstrapResult:
    return BootstrapResult(
        mean_diff=mean_diff,
        ci_low=mean_diff - 0.02,
        ci_high=mean_diff + 0.02,
        p_value=0.001,
        method="bootstrap",
        se=0.01,
        n_cases=n_clusters,
        n_clusters=n_clusters,
        n_resamples=2000,
        confidence=0.95,
    )


def _decide(r: BootstrapResult, p: float, *, gated: bool = True, min_clusters: int = 30) -> GateStatus:
    return decide(
        r, max_drop=0.03, p_adjusted=p, alpha=0.025, warn_p=0.10, min_clusters=min_clusters, gated=gated
    )


def test_fail() -> None:
    assert _decide(_r(), 0.001) is GateStatus.FAIL


def test_not_gated_passes() -> None:
    assert _decide(_r(), 0.001, gated=False) is GateStatus.PASS


def test_warn() -> None:
    assert _decide(_r(), 0.05) is GateStatus.WARN


def test_pass_not_significant() -> None:
    assert _decide(_r(), 0.3) is GateStatus.PASS


def test_significant_but_not_relevant_passes() -> None:
    assert _decide(_r(-0.02), 0.0001) is GateStatus.PASS


def test_relevance_boundary_is_strict() -> None:
    assert _decide(_r(-0.03), 0.0001) is GateStatus.PASS


def test_alpha_boundary_is_strict() -> None:
    assert _decide(_r(), 0.025) is GateStatus.WARN
    assert _decide(_r(), 0.10) is GateStatus.PASS


def test_insufficient_data() -> None:
    assert _decide(_r(n_clusters=10), 0.001) is GateStatus.INSUFFICIENT_DATA
    assert _decide(_r(n_clusters=10), 0.001, gated=False) is GateStatus.INSUFFICIENT_DATA


def test_insufficient_data_boundary() -> None:
    assert _decide(_r(n_clusters=29), 0.001) is GateStatus.INSUFFICIENT_DATA
    assert _decide(_r(n_clusters=30), 0.001) is GateStatus.FAIL


@pytest.mark.parametrize("p", [float("nan"), -0.1, 1.5])
def test_decide_rejects_bad_p(p: float) -> None:
    with pytest.raises(GateInputError):
        _decide(_r(), p)


@pytest.mark.parametrize(
    ("k", "n", "expected"),
    [
        (0, 300, GateStatus.PASS),
        (7, 300, GateStatus.WARN),
        (3, 120, GateStatus.PASS),
        (4, 120, GateStatus.WARN),
        (20, 300, GateStatus.FAIL),
        (0, 0, GateStatus.PASS),
    ],
)
def test_decide_absolute(k: int, n: int, expected: GateStatus) -> None:
    assert decide_absolute(k, n, max_value=0.02) is expected


@pytest.mark.parametrize(("k", "n", "mv"), [(5, 3, 0.02), (-1, 3, 0.02), (1, 3, 0.0), (1, 3, float("nan"))])
def test_decide_absolute_rejects_invalid(k: int, n: int, mv: float) -> None:
    with pytest.raises(GateInputError):
        decide_absolute(k, n, max_value=mv)
