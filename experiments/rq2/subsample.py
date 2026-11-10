"""Seeded, stratified subsample for the quota-bound GitHub Models arms (T5.4 S2, W1.6).

Strata are (label, hard_type); each stratum gets its share of ``size`` by largest remainders, and
items are drawn with a seeded generator, so the same seed gives the same subsample.
"""

from collections import defaultdict
from collections.abc import Sequence

import numpy as np
from rq2.calib_schema import CalibrationItem

DEFAULT_SIZE = 300


def _quotas(counts: dict[tuple[int, str], int], size: int) -> dict[tuple[int, str], int]:
    total = sum(counts.values())
    exact = {k: size * v / total for k, v in counts.items()}
    quotas = {k: int(x) for k, x in exact.items()}
    rest = size - sum(quotas.values())
    for key in sorted(exact, key=lambda k: (quotas[k] - exact[k], str(k)))[:rest]:
        quotas[key] += 1
    return quotas


def stratified_subsample(
    items: Sequence[CalibrationItem], size: int = DEFAULT_SIZE, seed: int = 1234
) -> list[CalibrationItem]:
    """Return ``size`` items stratified by label and hard type (all items when fewer).

    Args:
        items: One label set.
        size: Subsample size (300 per set for GitHub Models judges).
        seed: Seed of the draw.

    Returns:
        The subsample in the input order.
    """
    if len(items) <= size:
        return list(items)
    strata: dict[tuple[int, str], list[int]] = defaultdict(list)
    for i, item in enumerate(items):
        strata[(item.label, item.hard_type or "")].append(i)
    quotas = _quotas({k: len(v) for k, v in strata.items()}, size)
    rng = np.random.default_rng(seed)
    picked: set[int] = set()
    for key in sorted(strata, key=str):
        members = strata[key]
        chosen = rng.choice(len(members), size=quotas[key], replace=False)
        picked.update(members[int(j)] for j in chosen)
    return [item for i, item in enumerate(items) if i in picked]
