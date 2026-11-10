"""T5.4 S10/S11: anchor agreement, the N3 drift rule (D253) and the per-judge threshold (D308)."""

import pytest
from scipy import stats

from pruefstand.core.models.judge import JudgeVerdict
from pruefstand.judges.drift import (
    anchor_agreement,
    drift_threshold,
    flip_rate,
    is_drift,
    threshold_cap,
)


def _v(raw: int) -> JudgeVerdict:
    return JudgeVerdict(score=raw / 2, reason="", raw_score=raw, judge_model="m", cached=False)


def test_threshold_from_a_low_flip_rate_stays_five() -> None:
    assert drift_threshold(0.02, 50) == 5
    assert float(stats.binom.sf(4, 50, 0.02)) == pytest.approx(0.003, abs=1e-3)


def test_threshold_from_a_high_flip_rate_is_raised_to_eight() -> None:
    assert drift_threshold(0.06, 50) == 8
    assert float(stats.binom.sf(7, 50, 0.06)) <= 0.01
    assert float(stats.binom.sf(6, 50, 0.06)) == pytest.approx(0.029, abs=1e-3)


def test_is_drift_with_a_calibrated_threshold() -> None:
    assert not is_drift(0.88, 50, threshold=8)  # 6 changed
    assert is_drift(0.84, 50, threshold=8)  # 8 changed
    assert is_drift(0.90, 50, threshold=None)  # the N3 rule


def test_a_threshold_below_the_default_is_refused() -> None:
    with pytest.raises(ValueError, match="below"):
        is_drift(0.9, 50, threshold=4)


def test_anchor_agreement() -> None:
    same = [_v(2)] * 50
    assert anchor_agreement(same, same) == 1.0
    fresh = [_v(0)] * 5 + [_v(2)] * 45
    assert anchor_agreement(same, fresh) == pytest.approx(0.90)
    with pytest.raises(ValueError, match="length"):
        anchor_agreement(same, same[:49])


def test_n3_rule_examples() -> None:
    assert not is_drift(0.92, 50)
    assert is_drift(0.90, 50)
    assert not is_drift(0.98, 50, a0=1.0)  # one flip with a0 = 1.0 is not drift (AI12-03)
    assert is_drift(0.90, 50, a0=0.5)
    assert not is_drift(0.92, 50, a0=0.5)  # a0 never changes the result
    assert is_drift(0.75, 20)
    assert not is_drift(0.90, 20)


def test_invalid_inputs() -> None:
    with pytest.raises(ValueError, match="n >= 1"):
        is_drift(0.9, 0)
    with pytest.raises(ValueError, match="agreement"):
        is_drift(1.2, 50)


def test_flip_rate_upper_bound() -> None:
    rate, upper = flip_rate(0, 200)
    assert rate == 0.0
    assert 0.0 < upper < 0.02


def test_a_threshold_above_the_cap_means_the_judge_is_unfit() -> None:
    assert threshold_cap(50) == 10
    assert drift_threshold(0.067, 50) == 9  # the measured gemma3:12b bound
    with pytest.raises(ValueError, match="unfit"):
        drift_threshold(0.15, 50)
    with pytest.raises(ValueError, match="cap"):
        is_drift(0.70, 50, threshold=11)
    assert is_drift(0.80, 50, threshold=10)
