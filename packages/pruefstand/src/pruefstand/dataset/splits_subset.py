"""The judged subset of ``core`` (round 12 N1.1, round 13 P3.4).

``judged_subset_size`` cases, stratified by group (answerable, unanswerable, injection; shares as
in ``core``) and by tenant inside each group, no ``lang`` stratum. Whole clusters where possible;
the last cases of a group may come from a cluster that does not fit whole.
"""

from collections import defaultdict
from collections.abc import Sequence

import numpy as np

from pruefstand.core.models.testcase import TestCase
from pruefstand.dataset.splits_pool import ANSWERABLE, Role, allocate, role_of


def _group_of(case: TestCase) -> Role:
    return Role.ANSWERABLE if case.category in ANSWERABLE else role_of(case)


def _pick_in_group(cases: Sequence[TestCase], quota: int, rng: np.random.Generator) -> set[str]:
    """Pick ``quota`` cases by tenant share; whole clusters first, single cases to finish."""
    by_tenant: dict[str, list[TestCase]] = defaultdict(list)
    for c in cases:
        by_tenant[str(c.tenant)].append(c)
    shares = allocate(quota, {t: len(v) for t, v in by_tenant.items()})
    chosen: set[str] = set()
    for tenant in sorted(by_tenant):
        clusters: dict[str, list[TestCase]] = defaultdict(list)
        for c in by_tenant[tenant]:
            clusters[c.cluster_id].append(c)
        keys = sorted(clusters)
        left = shares[tenant]
        for i in rng.permutation(len(keys)):
            group = clusters[keys[i]]
            if len(group) <= left:
                chosen.update(c.id for c in group)
                left -= len(group)
        for c in sorted(by_tenant[tenant], key=lambda x: x.id):
            if left <= 0:
                break
            if c.id not in chosen:
                chosen.add(c.id)
                left -= 1
    return chosen


def flag_judged_subset(core: Sequence[TestCase], size: int, rng: np.random.Generator) -> set[str]:
    """Return the ids of the ``size`` core cases that form the judged subset.

    Args:
        core: The ``core`` cases.
        size: Subset size (0 switches it off).
        rng: Seeded generator.

    Returns:
        Case ids; group shares follow ``core`` by largest remainder (220/50/30 -> 110/25/15).
    """
    if size == 0 or not core:
        return set()
    groups: dict[Role, list[TestCase]] = defaultdict(list)
    for c in core:
        groups[_group_of(c)].append(c)
    shares = allocate(size, {g: len(v) for g, v in groups.items()})
    chosen: set[str] = set()
    for group in sorted(groups, key=lambda g: g.value):
        chosen |= _pick_in_group(groups[group], shares[group], rng)
    return chosen
