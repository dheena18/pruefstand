"""``full``: the refusal stratum and three nightly blocks (round 13 P3.1, D292).

Refusal stratum = ``unanswerable`` cases (``block=None``, run every night). Each block = exactly
``full_block_unperturbed`` unperturbed answerable cases (whole clusters, stratified by tenant x
category, block sizes within one cluster per stratum) plus at most ``full_block_perturbed``
perturbed variants of bases in the same block. Nothing else goes into ``full``.
"""

from collections import Counter

import numpy as np

from pruefstand.core.config import NUM_BLOCKS, SplitPlan
from pruefstand.core.enums import Split
from pruefstand.core.errors import DatasetError
from pruefstand.core.models.testcase import TestCase
from pruefstand.dataset.splits_pool import Cluster, Pool, Role, count, shuffled, stratified

Stratum = tuple[str, str]


def _stratum(cluster: Cluster) -> Stratum:
    return (cluster.tenant, cluster.category.value)


def _tenant(cluster: Cluster) -> str:
    return cluster.tenant


def usable_variants(cluster: Cluster) -> tuple[TestCase, ...]:
    """Variants whose base is an unperturbed case of the same cluster."""
    bases = {c.id for c in cluster.plain}
    return tuple(v for v in cluster.variants if v.base_id in bases)


def _with_variants(clusters: list[Cluster], budget: int, per_block: int) -> list[Cluster]:
    """Perturbed clusters (seeded order already applied) whose variants fit the total budget."""
    chosen: list[Cluster] = []
    for c in clusters:
        n = len(usable_variants(c))
        if 0 < n <= min(budget, per_block):
            chosen.append(c)
            budget -= n
    return chosen


class _Blocks:
    """Running state of the three blocks while clusters are dealt."""

    def __init__(self, plan: SplitPlan) -> None:
        self.plan = plan
        self.members: list[list[tuple[Cluster, bool]]] = [[] for _ in range(NUM_BLOCKS)]
        self.plain = [0] * NUM_BLOCKS
        self.variants = [0] * NUM_BLOCKS
        self.strata = [Counter[Stratum]() for _ in range(NUM_BLOCKS)]

    def fits(self, b: int, cluster: Cluster, *, with_variants: bool) -> bool:
        n = len(usable_variants(cluster)) if with_variants else 0
        return (
            self.plain[b] + cluster.size <= self.plan.full_block_unperturbed
            and self.variants[b] + n <= self.plan.full_block_perturbed
        )

    def add(self, b: int, cluster: Cluster, *, with_variants: bool) -> None:
        self.members[b].append((cluster, with_variants))
        self.plain[b] += cluster.size
        self.strata[b][_stratum(cluster)] += 1
        if with_variants:
            self.variants[b] += len(usable_variants(cluster))

    def deal(self, cluster: Cluster, target: list[int], *, with_variants: bool) -> bool:
        """Put ``cluster`` in a block that still has stratum quota and room; False if none."""
        options = [
            b
            for b in range(NUM_BLOCKS)
            if target[b] > 0 and self.fits(b, cluster, with_variants=with_variants)
        ]
        if not options:
            return False
        best = min(options, key=lambda b: (self.plain[b], self.variants[b], b))
        self.add(best, cluster, with_variants=with_variants)
        target[best] -= 1
        return True


def _choose_answerable(pool: Pool, plan: SplitPlan, rng: np.random.Generator) -> list[Cluster]:
    candidates = pool.select(lambda c: c.role is Role.ANSWERABLE)
    budget = NUM_BLOCKS * plan.full_block_perturbed
    perturbed = _with_variants(
        shuffled([c for c in candidates if usable_variants(c)], rng),
        budget,
        plan.full_block_perturbed,
    )
    total = NUM_BLOCKS * plan.full_block_unperturbed
    return stratified(candidates, _stratum, total, rng, first=[c.id for c in perturbed])


def _targets(n: int, totals: list[int]) -> list[int]:
    """Clusters per block for a stratum of ``n``: even, the remainder to the smallest blocks."""
    base, extra = divmod(n, NUM_BLOCKS)
    target = [base] * NUM_BLOCKS
    for b in sorted(range(NUM_BLOCKS), key=lambda x: (totals[x], x))[:extra]:
        target[b] += 1
    return target


def _deal_all(chosen: list[Cluster], plan: SplitPlan, rng: np.random.Generator) -> _Blocks:
    """Deal per stratum so blocks differ by at most one cluster in every tenant x category."""
    blocks = _Blocks(plan)
    strata: dict[Stratum, list[Cluster]] = {}
    for c in shuffled(chosen, rng):
        strata.setdefault(_stratum(c), []).append(c)
    budget = NUM_BLOCKS * plan.full_block_perturbed
    totals = [0] * NUM_BLOCKS
    for key in sorted(strata):
        members = sorted(strata[key], key=lambda c: not usable_variants(c))  # perturbed first
        target = _targets(len(members), totals)
        for b in range(NUM_BLOCKS):
            totals[b] += target[b]
        for c in members:
            n = len(usable_variants(c))
            if (
                n
                and sum(blocks.variants) + n <= budget
                and blocks.deal(c, target, with_variants=True)
            ):
                continue
            blocks.deal(c, target, with_variants=False)
    return blocks


def _top_up(blocks: _Blocks, spare: list[Cluster]) -> None:
    for b in range(NUM_BLOCKS):
        for c in spare:
            if blocks.plain[b] >= blocks.plan.full_block_unperturbed:
                break
            if blocks.fits(b, c, with_variants=False) and not any(
                c is m for part in blocks.members for m, _ in part
            ):
                blocks.add(b, c, with_variants=False)


def pick_full(pool: Pool, plan: SplitPlan, rng: np.random.Generator) -> list[TestCase]:
    """Fill the refusal stratum and the three blocks of ``full``.

    Returns:
        The cases with ``split=FULL`` and ``block`` set (``None`` for the refusal stratum); the
        surplus is not kept (the report counts it). Chosen clusters are removed from ``pool``.

    Raises:
        DatasetError: The refusal stratum or a block cannot be filled to its quota.
    """
    kept: list[TestCase] = []
    refusal = stratified(
        pool.select(lambda c: c.role is Role.UNANSWERABLE), _tenant, plan.full_refusal, rng
    )
    if count(refusal) != plan.full_refusal:
        got = count(refusal)
        msg = f"full: refusal stratum has {got} unanswerable cases, need {plan.full_refusal}"
        raise DatasetError(msg)
    for c in refusal:
        kept += [x.model_copy(update={"split": Split.FULL, "block": None}) for x in c.plain]
    pool.remove(refusal)
    if plan.full_block_unperturbed == 0:
        return kept
    blocks = _deal_all(_choose_answerable(pool, plan, rng), plan, rng)
    taken = {m.id for part in blocks.members for m, _ in part}
    _top_up(
        blocks,
        [
            c
            for c in shuffled(pool.select(lambda c: c.role is Role.ANSWERABLE), rng)
            if c.id not in taken
        ],
    )
    for b in range(NUM_BLOCKS):
        if blocks.plain[b] != plan.full_block_unperturbed:
            msg = (
                f"full: block {b} has {blocks.plain[b]} unperturbed answerable cases, "
                f"need {plan.full_block_unperturbed}"
            )
            raise DatasetError(msg)
        for c, with_variants in blocks.members[b]:
            keep = [*c.plain, *(usable_variants(c) if with_variants else ())]
            kept += [x.model_copy(update={"split": Split.FULL, "block": b}) for x in keep]
        pool.remove(c for c, _ in blocks.members[b])
    return kept
