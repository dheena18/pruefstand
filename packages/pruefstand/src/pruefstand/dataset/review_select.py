"""Smoke selection and the owner spot-check sample (T4.7a, SPEC §3.5 step 5).

``select_smoke`` is a rule, not a hand pick: model-reviewed ``ok`` items whose deterministic checks
passed, seeded and stratified so every category has at least ``min_per_category`` cases and the
hard-fail probes (leak, injection, system prompt) are included. ``sample_spotcheck`` draws the 50
items the owner checks; ``spotcheck_trust`` is the trust rule for the model review.
"""

from collections import defaultdict
from collections.abc import Callable, Sequence

import numpy as np

from pruefstand.core.enums import Category, Split
from pruefstand.core.errors import DatasetError
from pruefstand.core.models.dataset import ReviewItem, SpotDecision
from pruefstand.core.models.testcase import TestCase
from pruefstand.dataset.splits_pool import allocate

HARD_FAIL = frozenset(
    {
        Category.LEAK_PROBE,
        Category.INJECTION,
        Category.SYSTEM_PROMPT_EXTRACTION,
        Category.FILTER_BYPASS,
    }
)


def _clean_ok(items: Sequence[ReviewItem]) -> set[str]:
    return {i.case_id for i in items if i.verdict == "ok" and not i.reasons}


def _eligible_clusters(
    cases: Sequence[TestCase], items: Sequence[ReviewItem]
) -> dict[str, list[TestCase]]:
    """Whole clusters of unperturbed cases whose every case is a clean ``ok``."""
    clean = _clean_ok(items)
    groups: dict[str, list[TestCase]] = defaultdict(list)
    for case in sorted(cases, key=lambda c: c.id):
        if case.perturbation is None:
            groups[case.cluster_id].append(case)
    return {k: v for k, v in groups.items() if all(c.id in clean for c in v)}


def _of(category: Category) -> Callable[[TestCase], bool]:
    return lambda case: case.category is category


class _Picker:
    """Takes whole clusters in a seeded order until a rule is met."""

    def __init__(self, groups: dict[str, list[TestCase]], order: list[str]) -> None:
        self.groups, self.order = groups, order
        self.chosen: list[str] = []

    def count(self, match: Callable[[TestCase], bool]) -> int:
        return sum(1 for k in self.chosen for c in self.groups[k] if match(c))

    def fill(self, match: Callable[[TestCase], bool], minimum: int) -> int:
        """Take clusters holding a matching case until ``minimum`` match; return the count."""
        for key in self.order:
            if self.count(match) >= minimum:
                break
            if key not in self.chosen and any(match(c) for c in self.groups[key]):
                self.chosen.append(key)
        return self.count(match)

    def top_up(self, size: int) -> None:
        for key in self.order:
            have = self.count(lambda _c: True)
            if key not in self.chosen and have + len(self.groups[key]) <= size:
                self.chosen.append(key)


def select_smoke(
    cases: Sequence[TestCase],
    items: Sequence[ReviewItem],
    *,
    seed: int,
    size: int = 50,
    min_per_category: int = 3,
    min_probes: int = 5,
) -> list[TestCase]:
    """Select the ``smoke`` cases by rule.

    Args:
        cases: Candidate cases (unperturbed ones are considered).
        items: Review results; only clean ``ok`` items (no deterministic finding) qualify.
        seed: Seed; the same seed and input give the same ids.
        size: Number of cases.
        min_per_category: Least cases per category present in the eligible pool.
        min_probes: Least hard-fail probes (leak, injection, system prompt, filter bypass).

    Returns:
        The cases, sorted by id; whole clusters are taken, so the size is exact.

    Raises:
        DatasetError: A category has fewer eligible cases than ``min_per_category``, or the pool
            cannot give ``size`` cases.
    """
    rng = np.random.default_rng(seed)
    groups = _eligible_clusters(cases, items)
    picker = _Picker(groups, [list(groups)[int(i)] for i in rng.permutation(len(groups))])
    for category in sorted({c.category for v in groups.values() for c in v}, key=lambda c: c.value):
        if picker.fill(_of(category), min_per_category) < min_per_category:
            msg = f"smoke: fewer than {min_per_category} eligible {category.value} cases"
            raise DatasetError(msg)
    picker.fill(lambda c: c.category in HARD_FAIL, min_probes)
    picker.top_up(size)
    result = [c for k in picker.chosen for c in groups[k]]
    if len(result) != size:
        msg = f"smoke: {len(result)} eligible cases selected, need {size}"
        raise DatasetError(msg)
    return sorted(result, key=lambda c: c.id)


def sample_spotcheck(
    cases: Sequence[TestCase], items: Sequence[ReviewItem], *, seed: int, size: int = 50
) -> list[TestCase]:
    """Choose the cases of the owner spot-check.

    All ``smoke`` cases come first (their citations are always checked); the rest of ``size`` is a
    seeded draw from the other model-``ok`` and model-``fix`` cases, stratified by category and
    verdict. More smoke cases than ``size`` are all returned.

    Args:
        cases: The dataset's cases.
        items: Review results (``reject`` items are ignored, those cases are gone).
        seed: Seed of the draw.
        size: Target number of items.

    Returns:
        The cases, smoke first, then the draw, each sorted by id.
    """
    verdict = {i.case_id: i.verdict for i in items if i.verdict in {"ok", "fix"}}
    smoke = sorted((c for c in cases if c.split is Split.SMOKE), key=lambda c: c.id)
    pool: dict[tuple[str, str], list[TestCase]] = defaultdict(list)
    for case in sorted(cases, key=lambda c: c.id):
        if case.split is not Split.SMOKE and case.id in verdict:
            pool[(case.category.value, verdict[case.id])].append(case)
    want = max(size - len(smoke), 0)
    quota = allocate(
        min(want, sum(len(v) for v in pool.values())), {k: len(v) for k, v in pool.items()}
    )
    rng = np.random.default_rng(seed)
    drawn: list[TestCase] = []
    for key in sorted(pool):
        members = pool[key]
        drawn += [members[int(i)] for i in rng.permutation(len(members))[: quota.get(key, 0)]]
    return smoke + sorted(drawn, key=lambda c: c.id)


def spotcheck_trust(
    decisions: Sequence[SpotDecision], items: Sequence[ReviewItem], *, max_flag_rate: float = 0.10
) -> bool:
    """Return whether the model review is trusted after the owner spot-check.

    The owner flags an item when the citation or the plausibility is "no". The model review is not
    trusted when more than ``max_flag_rate`` of the spot-checked model-``ok`` items are flagged.

    Args:
        decisions: The owner's decisions.
        items: Review results (only the ``ok`` ones count).
        max_flag_rate: The tolerated share.

    Returns:
        True when the share of flagged model-``ok`` items is at most ``max_flag_rate`` (also when
        no ``ok`` item was checked).

    Examples:
        >>> spotcheck_trust([], [])
        True
    """
    ok = {i.case_id for i in items if i.verdict == "ok"}
    checked = [d for d in decisions if d.case_id in ok]
    flagged = sum(1 for d in checked if not (d.citation_ok and d.plausible))
    return flagged <= max_flag_rate * len(checked) + 1e-9
