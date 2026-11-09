"""Seeded sampling, balancing and the cluster-level dev/test split (T5.3, round 13 AI13-12).

The split puts whole ``cluster_id``s into ``dev`` (≈ 30 %) or ``test`` (≈ 70 %), balanced over
label and ``hard_type`` strata (see :func:`assign_calib_split`). Deviations are relative, so small
strata weigh as much as large ones.
"""

from collections import Counter, defaultdict
from collections.abc import Callable, Hashable, Sequence

import numpy as np
from rq2.calib_schema import CalibrationItem, is_positive

DEV_SHARE = 0.30
MAX_PASSES = 20


def seeded_order[T](values: Sequence[T], rng: np.random.Generator) -> list[T]:
    """Return ``values`` in a seeded random order."""
    return [values[int(i)] for i in rng.permutation(len(values))]


def round_robin_sample[T](
    rows: Sequence[T], key: Callable[[T], Hashable], n: int, rng: np.random.Generator
) -> list[T]:
    """Sample ``n`` rows spread over the groups of ``key`` (one per group per round, seeded)."""
    groups: dict[Hashable, list[T]] = defaultdict(list)
    for row in seeded_order(rows, rng):
        groups[key(row)].append(row)
    order = seeded_order(list(groups), rng)
    out: list[T] = []
    depth = 0
    while len(out) < n and any(len(groups[g]) > depth for g in order):
        out.extend(groups[g][depth] for g in order if len(groups[g]) > depth)
        depth += 1
    return out[:n]


def pick_hard(
    hard: Sequence[CalibrationItem], n: int, rng: np.random.Generator
) -> list[CalibrationItem]:
    """Pick ``n`` hard negatives spread evenly over their ``hard_type``s (seeded)."""
    return round_robin_sample(hard, lambda it: it.hard_type, n, rng)


def balance(
    positives: Sequence[CalibrationItem],
    hard: Sequence[CalibrationItem],
    other: Sequence[CalibrationItem],
    rng: np.random.Generator,
    hard_cap: float = 0.6,
) -> list[CalibrationItem]:
    """Down-sample to 50 % positives; hard negatives are kept before off-topic ones.

    Hard negatives fill up to ``hard_cap`` of the negative budget first (so off-topic negatives do
    not vanish, D861), off-topic negatives the rest, then any remaining hard negatives.

    Args:
        positives: Label-max items.
        hard: Hard-negative items.
        other: Off-topic negatives.
        rng: Seeded generator.
        hard_cap: Share of the negative budget reserved for hard negatives first.

    Returns:
        Positives followed by the chosen negatives; the negatives never outnumber the positives.
    """
    n_neg = min(len(positives), len(hard) + len(other))
    pos = seeded_order(positives, rng)[:n_neg]
    first = pick_hard(hard, min(len(hard), round(hard_cap * n_neg)), rng)
    rest_other = seeded_order(other, rng)[: n_neg - len(first)]
    chosen_ids = {it.item_id for it in first}
    spare = [it for it in seeded_order(hard, rng) if it.item_id not in chosen_ids]
    negatives = first + rest_other + spare[: n_neg - len(first) - len(rest_other)]
    return pos + negatives


def stratum(item: CalibrationItem) -> tuple[int, str]:
    """Return the split stratum of an item: (label, hard_type or ``-``)."""
    return item.label, item.hard_type or "-"


def _keys(item: CalibrationItem) -> tuple[str, ...]:
    label, hard_type = stratum(item)
    return "*", f"{label}|{hard_type}", f"type|{hard_type}"


def _delta(dev: Counter[str], counts: Counter[str], target: dict[str, float], sign: int) -> float:
    """Change of the summed squared relative ``dev`` deviation when a cluster moves by ``sign``."""
    total = 0.0
    for key, n in counts.items():
        scale = target[key] or 1.0
        before = (dev[key] - target[key]) / scale
        after = (dev[key] + sign * n - target[key]) / scale
        total += after * after - before * before
    return total


def assign_calib_split(
    items: Sequence[CalibrationItem], seed: int, dev_share: float = DEV_SHARE
) -> list[CalibrationItem]:
    """Assign ``calib_split`` by whole clusters, stratified by label and ``hard_type``.

    A greedy pass in seeded cluster order puts a cluster into ``dev`` when that lowers the summed
    squared relative deviation from ``dev_share`` over the set, every label x ``hard_type``
    stratum and every ``hard_type``; up to :data:`MAX_PASSES` improvement passes then move single
    clusters between ``dev`` and ``test`` while that lowers it further.

    Args:
        items: Items of one label set.
        seed: Split seed (1234 for v1).
        dev_share: Target ``dev`` share per stratum.

    Returns:
        The items, in input order, each with ``calib_split`` set.
    """
    per_cluster: dict[str, Counter[str]] = defaultdict(Counter)
    for it in items:
        per_cluster[it.cluster_id].update(_keys(it))
    totals: Counter[str] = Counter(k for it in items for k in _keys(it))
    target = {k: dev_share * n for k, n in totals.items()}
    order = seeded_order(sorted(per_cluster), np.random.default_rng(seed))
    dev: Counter[str] = Counter()
    in_dev: set[str] = set()
    for _ in range(MAX_PASSES):
        moved = False
        for cluster in order:
            sign = -1 if cluster in in_dev else 1
            if _delta(dev, per_cluster[cluster], target, sign) < -1e-12:
                in_dev.symmetric_difference_update({cluster})
                dev.update({k: sign * n for k, n in per_cluster[cluster].items()})
                moved = True
        if not moved:
            break
    return [
        it.model_copy(update={"calib_split": "dev" if it.cluster_id in in_dev else "test"})
        for it in items
    ]


def positive_share(items: Sequence[CalibrationItem]) -> float:
    """Return the share of binarised positives (0.0 for no items)."""
    return sum(is_positive(it) for it in items) / len(items) if items else 0.0
