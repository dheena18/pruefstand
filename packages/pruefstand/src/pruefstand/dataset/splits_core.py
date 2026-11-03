"""``smoke`` and ``core``: unperturbed whole clusters, stratified by tenant and category.

Both splits hold unperturbed cases only. A cluster with perturbed variants that lands here
keeps its base cases; the variants are dropped and counted (they would break the exact
``core`` composition and the "perturbed cases only in perturbed_all" rule, X3.6).
"""

from collections import Counter

import numpy as np

from pruefstand.core.config import SplitPlan
from pruefstand.core.enums import Category, Split
from pruefstand.core.errors import DatasetError
from pruefstand.core.models.testcase import TestCase
from pruefstand.dataset.splits_pool import (
    Cluster,
    Pool,
    Role,
    count,
    shuffled,
    stratified,
)


def _tenant_category(cluster: Cluster) -> tuple[str, str]:
    return (cluster.tenant, cluster.category.value)


def _tenant(cluster: Cluster) -> str:
    return cluster.tenant


def _category(cluster: Cluster) -> str:
    return cluster.category.value


def _place(chosen: list[Cluster], split: Split) -> list[TestCase]:
    return [x.model_copy(update={"split": split}) for c in chosen for x in c.plain]


def _guarantee_minimum(
    pool: list[Cluster], minimum: int, size: int, rng: np.random.Generator
) -> list[Cluster]:
    """Pick clusters until every category present has ``minimum`` cases (or fail)."""
    chosen: list[Cluster] = []
    seen: Counter[Category] = Counter()
    categories = sorted({x.category for c in pool for x in c.plain}, key=lambda c: c.value)
    for category in categories:
        for cluster in shuffled([c for c in pool if c not in chosen], rng):
            if seen[category] >= minimum:
                break
            if any(x.category is category for x in cluster.plain):
                chosen.append(cluster)
                seen.update(x.category for x in cluster.plain)
        if seen[category] < minimum:
            msg = f"smoke: only {seen[category]} {category.value} cases available, need {minimum}"
            raise DatasetError(msg)
    if count(chosen) > size:
        msg = f"smoke: {minimum} cases per category need {count(chosen)} cases, size is {size}"
        raise DatasetError(msg)
    return chosen


def pick_smoke(pool: Pool, plan: SplitPlan, rng: np.random.Generator) -> list[TestCase]:
    """Choose ``plan.smoke_size`` cases with at least ``smoke_min_per_category`` per category.

    Returns:
        The kept cases; the chosen clusters are removed from ``pool``.

    Raises:
        DatasetError: A category has too few cases, the minimum does not fit the size, or the
            pool cannot fill the size.
    """
    if plan.smoke_size == 0:
        return []
    candidates = pool.rest()
    chosen = _guarantee_minimum(candidates, plan.smoke_min_per_category, plan.smoke_size, rng)
    taken = {c.id for c in chosen}
    rest = [c for c in candidates if c.id not in taken]
    chosen += stratified(rest, _category, plan.smoke_size - count(chosen), rng)
    if count(chosen) != plan.smoke_size:
        msg = f"smoke: {count(chosen)} cases found, need {plan.smoke_size}"
        raise DatasetError(msg)
    pool.remove(chosen)
    return _place(chosen, Split.SMOKE)


def _answerable(pool: Pool, plan: SplitPlan, rng: np.random.Generator) -> list[Cluster]:
    candidates = pool.select(lambda c: c.role is Role.ANSWERABLE)
    lingual = [c for c in candidates if c.category is Category.CROSS_LINGUAL]
    chosen = stratified(lingual, _tenant, plan.core_min_cross_lingual, rng)
    taken = {c.id for c in chosen}
    rest = [c for c in candidates if c.id not in taken]
    return chosen + stratified(rest, _tenant_category, plan.core_answerable - count(chosen), rng)


def pick_core(pool: Pool, plan: SplitPlan, rng: np.random.Generator) -> list[TestCase]:
    """Choose the ``core`` cases: answerable, unanswerable and injection by tenant and category.

    Returns:
        The kept cases; the chosen clusters are removed from ``pool``.

    Raises:
        DatasetError: A group cannot be filled exactly (names the group and the counts).
    """
    if plan.core_size == 0:
        return []
    groups = {
        "answerable": _answerable(pool, plan, rng) if plan.core_answerable else [],
        "unanswerable": stratified(
            pool.select(lambda c: c.role is Role.UNANSWERABLE),
            _tenant,
            plan.core_unanswerable,
            rng,
        ),
        "injection": stratified(
            pool.select(lambda c: c.role is Role.INJECTION), _tenant, plan.core_injection, rng
        ),
    }
    wanted = {
        "answerable": plan.core_answerable,
        "unanswerable": plan.core_unanswerable,
        "injection": plan.core_injection,
    }
    for name, chosen in groups.items():
        if count(chosen) != wanted[name]:
            msg = f"core: {count(chosen)} {name} cases found, need {wanted[name]}"
            raise DatasetError(msg)
    kept: list[TestCase] = []
    for chosen in groups.values():
        kept += _place(chosen, Split.CORE)
        pool.remove(chosen)
    return kept
