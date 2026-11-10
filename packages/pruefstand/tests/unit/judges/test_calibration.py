"""T5.4 S1/S10: agreement statistics, specificity and the calibration table
(judges/calibration.py)."""

import math
import warnings

import numpy as np
import polars as pl
import pytest
from hypothesis import given
from hypothesis import strategies as st

from pruefstand.judges.calibration import (
    calibration_table,
    cluster_bootstrap_ci,
    cohens_kappa,
    gwet_ac1,
    spearman,
    specificity,
)


def test_kappa_of_identical_raters_is_one() -> None:
    assert cohens_kappa([0, 1, 1, 0, 1], [0, 1, 1, 0, 1]) == pytest.approx(1.0)


def test_kappa_known_binary_example() -> None:
    assert cohens_kappa([1, 1, 0, 0], [1, 0, 0, 0]) == pytest.approx(0.5)


def test_kappa_of_constant_raters_is_nan_with_a_warning() -> None:
    with pytest.warns(UserWarning, match="undefined"):
        value = cohens_kappa([1, 1, 1], [1, 1, 1])
    assert math.isnan(value)


def test_quadratic_kappa_matches_a_hand_computed_reference() -> None:
    a = [0, 1, 2, 2, 1, 0]
    b = [0, 2, 2, 1, 1, 0]
    # by hand: weights (i-j)^2/4; observed mean weight 1/12, expected 3/9 -> 1 - 0.25
    assert cohens_kappa(a, b, weights="quadratic") == pytest.approx(0.75, abs=1e-9)


def test_kappa_rejects_bad_input() -> None:
    with pytest.raises(ValueError, match="length"):
        cohens_kappa([1, 0], [1])
    with pytest.raises(ValueError, match="empty"):
        cohens_kappa([], [])


def test_ac1_known_example() -> None:
    assert gwet_ac1([1, 1, 0, 0], [1, 0, 0, 0]) == pytest.approx(0.5294117647, abs=1e-9)


def test_spearman_examples() -> None:
    assert spearman([1, 2, 3], [1, 2, 3]) == pytest.approx(1.0)
    assert spearman([1, 2, 3], [3, 2, 1]) == pytest.approx(-1.0)
    assert spearman([1, 1, 2], [1, 2, 3]) == pytest.approx(0.866, abs=1e-3)


def test_specificity_with_wilson_interval() -> None:
    preds = [0] * 125 + [1] * 25
    tnr, low, high = specificity([0] * 150, preds)
    assert tnr == pytest.approx(125 / 150)
    assert low == pytest.approx(0.766, abs=1e-3)
    assert low < tnr < high


def test_specificity_needs_a_negative() -> None:
    with pytest.raises(ValueError, match="negative"):
        specificity([1, 1], [1, 0])


def _clustered(rng: np.random.Generator) -> pl.DataFrame:
    values = np.repeat(rng.integers(0, 2, size=20), 5)  # 5 identical items per cluster
    return pl.DataFrame({"cluster_id": np.repeat(np.arange(20), 5), "x": values, "row": range(100)})


def _mean(df: pl.DataFrame) -> float:
    return float(df["x"].to_numpy().mean())


def test_cluster_bootstrap_is_seeded_contains_the_estimate_and_is_wider_than_pairs() -> None:
    df = _clustered(np.random.default_rng(7))
    first = cluster_bootstrap_ci(_mean, df, "cluster_id", 500, 0.95, np.random.default_rng(1234))
    again = cluster_bootstrap_ci(_mean, df, "cluster_id", 500, 0.95, np.random.default_rng(1234))
    pairs = cluster_bootstrap_ci(_mean, df, "row", 500, 0.95, np.random.default_rng(1234))
    assert first == again
    assert first[0] <= _mean(df) <= first[1]
    assert first[1] - first[0] > pairs[1] - pairs[0]


def test_an_all_negative_subset_gives_kappa_nan_or_zero() -> None:
    labels = [0] * 30
    preds = [0] * 24 + [1] * 6
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        value = cohens_kappa(labels, preds)
    assert math.isnan(value) or value == 0.0  # why kappa is never computed on hard negatives


def _hand_rows() -> tuple[pl.DataFrame, pl.DataFrame]:
    labels = pl.DataFrame(
        {
            "item_id": ["a", "b", "c", "d"],
            "label_set": ["correctness"] * 4,
            "metric": ["answer_correctness"] * 4,
            "label": [2, 2, 0, 1],
            "cluster_id": ["c1", "c2", "c3", "c4"],
            "hard_negative": [False, False, False, True],
            "hard_type": [None, None, None, "partial_answer"],
            "label_origin": ["construction"] * 4,
        }
    )
    verdicts = pl.DataFrame(
        {
            "item_id": ["a", "b", "c", "d"],
            "judge": ["ollama/gemma3:12b"] * 4,
            "metric": ["answer_correctness"] * 4,
            "score": [2, 1, 0, 0],
        }
    )
    return labels, verdicts


def test_calibration_table_on_four_hand_rows() -> None:
    table = calibration_table(*_hand_rows())
    row = table.filter(pl.col("stratum") == "all").row(0, named=True)
    assert row["n"] == 4
    assert row["prevalence"] == pytest.approx(0.5)
    assert row["accuracy"] == pytest.approx(0.75)
    hard = table.filter(pl.col("stratum") == "hard_negative").row(0, named=True)
    assert hard["kappa"] is None
    assert hard["ac1"] is None
    assert hard["specificity"] == pytest.approx(1.0)
    assert hard["specificity_ci_low"] is not None


@given(st.lists(st.tuples(st.integers(0, 2), st.integers(0, 2)), min_size=2, max_size=40))
def test_kappa_is_bounded_and_symmetric(pairs: list[tuple[int, int]]) -> None:
    a = [p[0] for p in pairs]
    b = [p[1] for p in pairs]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ab = cohens_kappa(a, b)
        ba = cohens_kappa(b, a)
    if math.isnan(ab):
        assert math.isnan(ba)
        return
    assert -1.0 - 1e-9 <= ab <= 1.0 + 1e-9
    assert ab == pytest.approx(ba)
