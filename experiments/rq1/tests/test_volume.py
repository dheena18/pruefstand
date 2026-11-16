"""T7.3 S2 (pure part): equal retrieved text volume for the chunking arms (P3.2, AI13-05)."""

import pytest
from hypothesis import given
from hypothesis import strategies as st
from rq1.volume import TOKEN_BUDGET, take_until_budget


def test_per_paragraph_and_fixed_chunks_hand_the_same_volume() -> None:
    per_paragraph = take_until_budget([1800, 1800, 1800])
    fixed = take_until_budget([512] * 10)
    assert per_paragraph == (1800, 1800, 496)  # 3 chunks, the last cut
    assert fixed == (512,) * 8  # 8 chunks
    assert sum(per_paragraph) == sum(fixed) == TOKEN_BUDGET == 4096


def test_fewer_tokens_than_the_budget_keeps_every_chunk() -> None:
    assert take_until_budget([100, 200]) == (100, 200)


@pytest.mark.parametrize("budget", [0, -1])
def test_non_positive_budget_is_refused(budget: int) -> None:
    with pytest.raises(ValueError, match="budget"):
        take_until_budget([10], budget)


def test_negative_token_count_is_refused() -> None:
    with pytest.raises(ValueError, match="negative"):
        take_until_budget([10, -1])


@given(
    st.lists(st.integers(min_value=0, max_value=3000), max_size=30),
    st.integers(min_value=1, max_value=9000),
)
def test_never_exceeds_the_budget_and_keeps_rank_order(counts: list[int], budget: int) -> None:
    kept = take_until_budget(counts, budget)
    assert sum(kept) == min(budget, sum(counts))
    assert all(k == c for k, c in zip(kept[:-1], counts, strict=False))
