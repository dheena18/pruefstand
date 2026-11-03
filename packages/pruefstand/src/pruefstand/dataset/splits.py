"""``assign_splits``: seeded, cluster-preserving split assignment (interfaces §14, T4.1 S2).

Stages draw whole clusters from the pool in a fixed order, so the first stages are never starved:
``robust_pr``, ``rq1`` (bases of perturbed clusters), ``smoke``, ``core``, ``full`` (refusal
stratum + three nightly blocks), then the judged subset of ``core``. Whatever no stage takes
(surplus, mixed-role clusters, variants outside their quota) is *dropped and counted* in the
``SplitReport``; ``assign_splits`` returns only the kept cases.
"""

from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np

from pruefstand.core.config import SplitPlan
from pruefstand.core.enums import Split
from pruefstand.core.logging import get_logger
from pruefstand.core.models.testcase import TestCase
from pruefstand.dataset.splits_core import pick_core, pick_smoke
from pruefstand.dataset.splits_full import pick_full
from pruefstand.dataset.splits_perturbed import pick_perturbed
from pruefstand.dataset.splits_pool import Pool
from pruefstand.dataset.splits_subset import flag_judged_subset

_ORDER = {s: i for i, s in enumerate(Split)}
_log = get_logger(__name__)


def _reasons(dropped: Sequence[TestCase], used: set[str], pooled: set[str]) -> dict[str, int]:
    """Count ``dropped`` cases by reason (see ``SplitReport.reasons``)."""
    found: Counter[str] = Counter()
    for c in dropped:
        if c.cluster_id not in pooled:
            found["mixed_role"] += 1
        elif c.cluster_id not in used:
            found["surplus"] += 1
        else:
            found["variants_dropped" if c.perturbation else "trimmed"] += 1
    return dict(found)


@dataclass(frozen=True)
class SplitReport:
    """Result of one assignment.

    Attributes:
        cases: The kept cases with ``split``, ``block`` and ``judged_subset`` set, ordered by
            split then id.
        dropped: Cases no split took (surplus, mixed-role clusters, surplus variants).
        reasons: Why cases were dropped: ``surplus`` (cluster unused), ``mixed_role`` (cluster
            without a base or with several roles), ``trimmed`` (cut from a used cluster),
            ``variants_dropped`` (variants of a used cluster outside its quota). Sums to
            ``len(dropped)``.
        n_perturbed: Perturbed cases per split (``robust_pr``, ``rq1``, ``full``): the real
            ``perturbed_all`` n the manifest and the reports state.
    """

    cases: tuple[TestCase, ...]
    dropped: tuple[TestCase, ...]
    n_perturbed: dict[Split, int]
    reasons: dict[str, int]


def assign_splits_report(
    cases: Sequence[TestCase], plan: SplitPlan, rng: np.random.Generator
) -> SplitReport:
    """Assign every case to a split (whole clusters), set blocks and the judged subset.

    Args:
        cases: Generated cases; their ``split`` is ignored. ``cluster_id`` must be set.
        plan: Sizes and quotas.
        rng: Seeded generator; the same seed and input give the same assignment.

    Returns:
        The report with kept cases, dropped cases and perturbed counts.

    Raises:
        DatasetError: A quota cannot be met (names the split and the shortfall).
    """
    pool = Pool.from_cases(cases)
    pool_ids = {c.id for c in pool.rest()}
    kept: list[TestCase] = []
    stages: tuple[Callable[[], list[TestCase]], ...] = (
        lambda: pick_perturbed(pool, plan.robust_pr_bases, Split.ROBUST_PR, plan),
        lambda: pick_perturbed(pool, plan.rq1_bases, Split.RQ1, plan),
        lambda: pick_smoke(pool, plan, rng),
        lambda: pick_core(pool, plan, rng),
        lambda: pick_full(pool, plan, rng),
    )
    for stage in stages:
        kept += stage()
    subset = flag_judged_subset(
        [c for c in kept if c.split is Split.CORE], plan.judged_subset_size, rng
    )
    kept = [c.model_copy(update={"judged_subset": True}) if c.id in subset else c for c in kept]
    kept.sort(key=lambda c: (_ORDER[c.split], c.id))
    placed = {c.id for c in kept}
    dropped = [c for c in cases if c.id not in placed]
    perturbed = Counter(c.split for c in kept if c.perturbation)
    reasons = _reasons(dropped, {c.cluster_id for c in kept}, pool_ids)
    if reasons:
        _log.warning("splits_dropped", total=len(dropped), reasons=reasons)
    return SplitReport(
        tuple(kept), tuple(sorted(dropped, key=lambda c: c.id)), dict(perturbed), reasons
    )


def assign_splits(
    cases: Sequence[TestCase], plan: SplitPlan, rng: np.random.Generator
) -> list[TestCase]:
    """Assign splits; whole clusters stay in one split (interfaces §14).

    Sets ``split``, ``block`` (``full`` only: refusal stratum ``None``, others 0/1/2) and
    ``judged_subset`` (150 ``core`` cases) and nothing else. See ``assign_splits_report`` for the
    dropped cases and the perturbed counts.

    Args:
        cases: Generated cases with ``cluster_id`` set.
        plan: Sizes and quotas.
        rng: Seeded generator.

    Returns:
        The kept cases ordered by split, then id.

    Raises:
        DatasetError: A quota cannot be met.
    """
    return list(assign_splits_report(cases, plan, rng).cases)


def assignment_summary(cases: Sequence[TestCase], seed: int) -> tuple[dict[str, int], int, int]:
    """Return the manifest fields ``(blocks, judged_subset, assignment_seed)`` of ``cases``.

    Args:
        cases: Assigned cases.
        seed: The seed ``assign_splits`` used.

    Returns:
        ``blocks`` (keys ``"refusal"``, ``"0"``, ``"1"``, ``"2"``; empty when there is no ``full``
        case), the number of ``judged_subset`` cases, and ``seed``.

    Examples:
        >>> assignment_summary([], 7)
        ({}, 0, 7)
    """
    full = [c for c in cases if c.split is Split.FULL]
    blocks: dict[str, int] = {}
    if full:
        counts = Counter(c.block for c in full)
        blocks = {"refusal": counts[None], **{str(b): counts[b] for b in (0, 1, 2)}}
    return blocks, sum(1 for c in cases if c.judged_subset), seed
