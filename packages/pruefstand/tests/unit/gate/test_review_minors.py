"""Review follow-ups for T1.6: recomputed p, CI and se, switch boundaries, lazy scipy."""

import math
import subprocess
import sys

import numpy as np
import pytest
from pydantic import ValidationError
from scipy import stats as sps

from pruefstand.core.errors import GateInputError
from pruefstand.core.ids import CaseId
from pruefstand.core.models.gate import BootstrapResult, ScoreTable
from pruefstand.gate.stats import paired_cluster_bootstrap, sign_test_p

ALPHA = 0.025


def _ids(n: int) -> np.ndarray:
    return np.array([f"d{i}" for i in range(n)])


def _boot(d: np.ndarray, b: int = 2000, seed: int = 5, conf: float = 0.95) -> BootstrapResult:
    return paired_cluster_bootstrap(
        d, _ids(d.size), n_resamples=b, confidence=conf, rng=np.random.default_rng(seed)
    )


def _replicates(d: np.ndarray, b: int, seed: int) -> tuple[float, np.ndarray]:
    """Independent recomputation of the corrected replicates (one case per cluster, one chunk)."""
    d = d[np.argsort(_ids(d.size))]  # the implementation indexes clusters in sorted-id order
    k = d.size
    idx = np.random.default_rng(seed).integers(0, k, size=(b, k))
    boot = d[idx].mean(axis=1)
    mean = float(d.mean())
    c = math.sqrt(k / (k - 1)) * sps.t.isf(ALPHA, k - 1) / sps.norm.isf(ALPHA)
    return mean, mean + (boot - mean) * c


def _tie_data() -> np.ndarray:
    d = np.zeros(40)
    d[:6], d[6:12] = 1.0, -1.0
    return d


def test_p_counts_ties_as_not_a_drop() -> None:
    d = _tie_data()
    _, bc = _replicates(d, 2000, 5)
    assert (bc >= 0).sum() > (bc > 0).sum()  # the data really produce exact ties at 0
    r = _boot(d)
    assert r.method == "bootstrap"
    assert r.p_value == pytest.approx((1 + (bc >= 0).sum()) / 2001, abs=1e-15)


@pytest.mark.parametrize("conf", [0.90, 0.95])
def test_ci_is_the_two_sided_percentile_interval(conf: float) -> None:
    d = np.random.default_rng(3).normal(-0.02, 0.1, 40)
    _, bc = _replicates(d, 2000, 5)
    r = _boot(d, conf=conf)
    lo, hi = np.quantile(bc, [(1 - conf) / 2, (1 + conf) / 2])
    assert (r.ci_low, r.ci_high) == pytest.approx((lo, hi), abs=1e-12)


def test_ci_90_is_narrower_than_95() -> None:
    d = np.random.default_rng(3).normal(-0.02, 0.1, 40)
    r90, r95 = _boot(d, conf=0.90), _boot(d, conf=0.95)
    assert r90.ci_high - r90.ci_low < r95.ci_high - r95.ci_low


def test_se_is_sample_standard_deviation_of_corrected_replicates() -> None:
    d = np.random.default_rng(3).normal(-0.02, 0.1, 40)
    _, bc = _replicates(d, 50, 5)
    assert _boot(d, b=50).se == pytest.approx(bc.std(ddof=1), rel=1e-12)


def _with_nonzero(n_nonzero: int, tiny: float = 0.0) -> np.ndarray:
    d = np.zeros(40)
    d[:n_nonzero] = -1.0
    d[39] = tiny
    return d


def test_switch_at_exactly_nine_and_ten_nonzero_clusters() -> None:
    assert _boot(_with_nonzero(9)).method == "sign_test"
    assert _boot(_with_nonzero(10)).method == "bootstrap"


def test_zero_tolerance_is_relative_to_largest_diff() -> None:
    assert _boot(_with_nonzero(9, tiny=5e-13)).method == "sign_test"  # counts as zero
    assert _boot(_with_nonzero(9, tiny=2e-12)).method == "bootstrap"  # counts as non-zero


@pytest.mark.parametrize("rng", [None, 7, "x"])
def test_rng_must_be_a_generator(rng: object) -> None:
    with pytest.raises(GateInputError, match="rng"):
        paired_cluster_bootstrap(
            np.zeros(5),
            _ids(5),
            n_resamples=10,
            confidence=0.95,
            rng=rng,  # type: ignore[arg-type]  # wrong type on purpose
        )


def test_score_table_rejects_non_finite_values_and_duplicate_case_ids() -> None:
    base: dict[str, object] = {
        "metric": "m",
        "higher_is_better": True,
        "case_ids": (CaseId("a"), CaseId("b")),
        "cluster_ids": ("x", "y"),
        "values": (1.0, 0.0),
        "slices": {},
    }
    ScoreTable.model_validate(base)
    for bad in ({"values": (1.0, float("nan"))}, {"values": (float("inf"), 0.0)}):
        with pytest.raises(ValidationError):
            ScoreTable.model_validate({**base, **bad})
    with pytest.raises(ValidationError, match="duplicate"):
        ScoreTable.model_validate({**base, "case_ids": (CaseId("a"), CaseId("a"))})


@pytest.mark.parametrize("m", [1, 9, 40, 1000, 1001, 5000])
def test_sign_test_matches_binomial_cdf(m: int) -> None:
    rng = np.random.default_rng(m)
    x = rng.choice([-1.0, 1.0], size=m)
    n_pos = int((x > 0).sum())
    assert sign_test_p(x) == pytest.approx(
        float(sps.binom.cdf(n_pos, m, 0.5)), rel=1e-9, abs=1e-300
    )


def test_importing_the_gate_does_not_import_scipy() -> None:
    code = (
        "import sys, pruefstand.gate.stats, pruefstand.gate.decision;"
        " sys.exit('scipy' in sys.modules)"
    )
    assert subprocess.run([sys.executable, "-c", code], check=False).returncode == 0  # noqa: S603
