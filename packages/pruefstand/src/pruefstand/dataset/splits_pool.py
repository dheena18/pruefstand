"""Building blocks of ``assign_splits``: clusters, the pool, proportional allocation, drawing.

A *cluster* is every case sharing a ``cluster_id``. Each stage of ``assign_splits`` draws whole
clusters from the ``Pool`` (so a cluster is never split) using seeded shuffles, and allocates
quotas to strata by the largest-remainder method.
"""

from collections import Counter
from collections.abc import Callable, Hashable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

import numpy as np

from pruefstand.core.enums import Category
from pruefstand.core.models.testcase import TestCase

ANSWERABLE = frozenset(
    {Category.FACTUAL, Category.MULTI_HOP, Category.COMPARISON, Category.CROSS_LINGUAL}
)
PROBES = frozenset({Category.LEAK_PROBE, Category.SYSTEM_PROMPT_EXTRACTION, Category.FILTER_BYPASS})


class Role(StrEnum):
    """What a case is for; a cluster with several roles is not placed (builders avoid them)."""

    ANSWERABLE = "answerable"
    UNANSWERABLE = "unanswerable"
    INJECTION = "injection"
    PROBE = "probe"


def role_of(case: TestCase) -> Role:
    """Return the role of ``case`` by its category."""
    if case.category in ANSWERABLE:
        return Role.ANSWERABLE
    if case.category is Category.UNANSWERABLE:
        return Role.UNANSWERABLE
    if case.category is Category.INJECTION:
        return Role.INJECTION
    return Role.PROBE


@dataclass(frozen=True)
class Cluster:
    """All cases of one ``cluster_id``: the unperturbed ones and the perturbed variants."""

    id: str
    plain: tuple[TestCase, ...]
    variants: tuple[TestCase, ...]

    @property
    def role(self) -> Role | None:
        """The one role of the unperturbed cases, ``None`` when mixed or without a base."""
        roles = {role_of(c) for c in self.plain}
        return roles.pop() if len(roles) == 1 else None

    @property
    def tenant(self) -> str:
        """Tenant of the first unperturbed case."""
        return str(self.plain[0].tenant)

    @property
    def category(self) -> Category:
        """Category of the first unperturbed case (the stratum key of mixed-category clusters)."""
        return self.plain[0].category

    @property
    def size(self) -> int:
        """Number of unperturbed cases (what a quota counts)."""
        return len(self.plain)

    @property
    def cases(self) -> tuple[TestCase, ...]:
        """Unperturbed cases followed by the variants."""
        return self.plain + self.variants

    def trimmed(self, n: int) -> "Cluster":
        """The cluster cut to its first ``n`` unperturbed cases (by id) and their variants."""
        plain = self.plain[:n]
        ids = {c.id for c in plain}
        return Cluster(self.id, plain, tuple(v for v in self.variants if v.base_id in ids))


class Pool:
    """The clusters not yet placed; stages ``select`` candidates and ``remove`` what they use."""

    def __init__(self, clusters: Iterable[Cluster]) -> None:
        self._clusters = {c.id: c for c in clusters}

    @classmethod
    def from_cases(cls, cases: Iterable[TestCase]) -> "Pool":
        """Group ``cases`` by ``cluster_id``.

        Clusters without an unperturbed case (variants without a base) or with more than one
        role are left out of the pool (they end up in the report's ``dropped``).
        """
        plain: dict[str, list[TestCase]] = {}
        variants: dict[str, list[TestCase]] = {}
        for c in sorted(cases, key=lambda x: x.id):
            (variants if c.perturbation else plain).setdefault(c.cluster_id, []).append(c)
        clusters = (
            Cluster(cid, tuple(plain.get(cid, ())), tuple(variants.get(cid, ())))
            for cid in sorted(plain.keys() | variants.keys())
        )
        return cls(c for c in clusters if c.role is not None)

    def select(self, keep: Callable[[Cluster], bool]) -> list[Cluster]:
        """Return the remaining clusters for which ``keep`` is true, sorted by id."""
        return [c for _, c in sorted(self._clusters.items()) if keep(c)]

    def remove(self, chosen: Iterable[Cluster]) -> None:
        """Take ``chosen`` out of the pool."""
        for c in chosen:
            self._clusters.pop(c.id, None)

    def rest(self) -> list[Cluster]:
        """Every remaining cluster, sorted by id."""
        return self.select(lambda _: True)


def shuffled(clusters: Sequence[Cluster], rng: np.random.Generator) -> list[Cluster]:
    """Return ``clusters`` sorted by id, then permuted by ``rng`` (input order never matters)."""
    ordered = sorted(clusters, key=lambda c: c.id)
    return [ordered[i] for i in rng.permutation(len(ordered))]


def allocate[K: Hashable](total: int, capacity: Mapping[K, int]) -> dict[K, int]:
    """Split ``total`` over the keys in proportion to ``capacity`` (largest remainder, capped).

    Never gives a key more than its capacity; ties are broken by the sorted key order.

    Examples:
        >>> allocate(10, {"a": 50, "b": 30, "c": 20})
        {'a': 5, 'b': 3, 'c': 2}
        >>> allocate(10, {"a": 1, "b": 3})
        {'a': 1, 'b': 3}
        >>> allocate(7, {"a": 1, "b": 100})
        {'a': 0, 'b': 7}
    """
    keys = sorted(capacity, key=repr)
    out = dict.fromkeys(keys, 0)
    remaining = min(total, sum(capacity.values()))
    while remaining > 0:
        active = [k for k in keys if out[k] < capacity[k]]
        weight = sum(capacity[k] for k in active)
        shares = {k: remaining * capacity[k] / weight for k in active}
        gave = 0
        for k in active:
            take = min(int(shares[k]), capacity[k] - out[k])
            out[k] += take
            gave += take
        order = sorted(active, key=lambda k: (-(shares[k] - int(shares[k])), repr(k)))
        for k in order:
            if gave >= remaining:
                break
            if out[k] < capacity[k]:
                out[k] += 1
                gave += 1
        remaining -= gave
    return out


def draw(ordered: Sequence[Cluster], quota: int) -> list[Cluster]:
    """Take clusters in order while they fit the remaining ``quota``.

    A cluster is never split over two splits; when nothing fits any more the first skipped
    cluster is *trimmed* to the missing cases (its other cases are dropped and counted), so a
    quota is met exactly whenever enough cases exist.
    """
    chosen: list[Cluster] = []
    skipped: list[Cluster] = []
    left = quota
    for c in ordered:
        if left <= 0:
            break
        if c.size <= left:
            chosen.append(c)
            left -= c.size
        else:
            skipped.append(c)
    if left > 0 and skipped:
        chosen.append(skipped[0].trimmed(left))
    return chosen


def count(clusters: Iterable[Cluster]) -> int:
    """Total unperturbed cases of ``clusters``."""
    return sum(c.size for c in clusters)


def stratified[K: Hashable](
    candidates: Sequence[Cluster],
    key: Callable[[Cluster], K],
    total: int,
    rng: np.random.Generator,
    *,
    first: Iterable[str] = (),
    quotas: Mapping[K, int] | None = None,
) -> list[Cluster]:
    """Draw about ``total`` cases of whole clusters from ``candidates``, proportional per stratum.

    Args:
        candidates: Eligible clusters.
        key: Stratum of a cluster (e.g. ``(tenant, category)``).
        total: Cases wanted.
        rng: Seeded generator (one permutation of all candidates).
        first: Cluster ids tried before the others inside their stratum.
        quotas: Per-stratum quotas; defaults to ``allocate(total, capacity)``.

    Returns:
        The chosen clusters; if strata run dry or a cluster does not fit, a final top-up pass takes
        any remaining cluster that still fits. The caller checks the count.
    """
    priority = set(first)
    order = sorted(shuffled(candidates, rng), key=lambda c: c.id not in priority)
    if quotas is None:
        capacity = Counter[K]()
        for c in candidates:
            capacity[key(c)] += c.size
        quotas = allocate(total, capacity)
    chosen: list[Cluster] = []
    for k in sorted(quotas, key=repr):
        chosen += draw([c for c in order if key(c) == k], quotas[k])
    taken = {c.id for c in chosen}
    chosen += draw([c for c in order if c.id not in taken], total - count(chosen))
    return chosen
