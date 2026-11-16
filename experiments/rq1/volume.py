"""Equal retrieved text volume for the RQ1 chunking arms (round 13 P3.2, AI13-05, binding).

The chunking arms are compared at equal total retrieved tokens, not equal ``top_k``: every config
takes the ranked chunks until the pre-registered budget is reached and cuts the last chunk at the
budget, so per-§ chunks and 512-token sub-chunks hand the same text volume to scoring and
generation.
"""

from collections.abc import Sequence

TOKEN_BUDGET = 4096
"""Pre-registered retrieved-token budget per query, counted with the generator tokenizer."""


def take_until_budget(chunk_tokens: Sequence[int], budget: int = TOKEN_BUDGET) -> tuple[int, ...]:
    """Return how many tokens of each ranked chunk are kept under ``budget``.

    Args:
        chunk_tokens: token count of each chunk, in rank order.
        budget: total tokens kept per query.

    Returns:
        Tokens kept per chunk, in rank order; chunks past the budget are left out and the last
        kept chunk is cut at the budget.

    Raises:
        ValueError: ``budget`` is not positive or a token count is negative.

    Examples:
        >>> take_until_budget([1800, 1800, 1800])
        (1800, 1800, 496)
        >>> len(take_until_budget([512] * 10))
        8
    """
    if budget <= 0:
        msg = f"budget must be positive, got {budget}"
        raise ValueError(msg)
    if any(count < 0 for count in chunk_tokens):
        msg = "token counts must not be negative"
        raise ValueError(msg)
    kept: list[int] = []
    left = budget
    for count in chunk_tokens:
        if left == 0:
            break
        take = min(count, left)
        kept.append(take)
        left -= take
    return tuple(kept)
