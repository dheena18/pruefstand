"""Which target endpoint a case uses (R11 D218/D222, R13 P3.4)."""

from dataclasses import dataclass
from typing import Literal

from pruefstand.core.enums import Category, Split
from pruefstand.core.models.testcase import TestCase

_ANSWERABLE = frozenset(
    {Category.FACTUAL, Category.MULTI_HOP, Category.COMPARISON, Category.CROSS_LINGUAL}
)


@dataclass(frozen=True)
class Route:
    """``mode`` is the endpoint family; ``reason`` explains ``not_applicable`` answer metrics."""

    mode: Literal["answer", "retrieve"]
    reason: str | None


def route_case(case: TestCase, *, judged_subset: bool) -> Route:
    """Decide between ``/v1/query`` and ``/v1/retrieve`` for ``case``.

    ``robust_pr`` cases always retrieve only. With ``judged_subset`` a ``core`` answerable case
    outside the subset is not generated either (R13 P3.4); unanswerable, injection and every
    other case are generated as usual.

    Args:
        case: The test case.
        judged_subset: Whether the run limits generation and judging to the subset.

    Returns:
        The route; ``reason`` is set exactly for ``retrieve``.

    Examples:
        >>> Route("retrieve", "retrieve_mode").mode
        'retrieve'
    """
    if case.split is Split.ROBUST_PR:
        return Route("retrieve", "retrieve_mode")
    outside = judged_subset and not case.judged_subset
    if outside and case.split is Split.CORE and case.category in _ANSWERABLE:
        return Route("retrieve", "not_in_judged_subset")
    return Route("answer", None)
