"""T5.4 S6: the bias delta and its cluster bootstrap CI."""

import polars as pl
from rq2.bias import bias_delta


def test_identical_scores_give_zero_delta_and_a_zero_ci() -> None:
    df = pl.DataFrame(
        {"cluster_id": ["a", "b", "c"], "base": [1.0, 0.5, 0.0], "perturbed": [1.0, 0.5, 0.0]}
    )
    assert bias_delta(df) == (0.0, 0.0, 0.0)


def test_a_uniform_drop_is_the_delta() -> None:
    df = pl.DataFrame({"cluster_id": ["a", "b"], "base": [1.0, 1.0], "perturbed": [0.5, 0.5]})
    delta, low, high = bias_delta(df)
    assert delta == -0.5
    assert low == high == -0.5
