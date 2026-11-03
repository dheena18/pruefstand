"""``robust_pr`` and ``rq1``: bases chosen by applicability, one base per source document.

The input already holds the *applicable* (base, perturbation) pairs: a perturbation that does not
change a base produced no variant (SPEC §4.1). The applicability score of a base is the number of
distinct perturbation names among its variants (round-8 W3.14).
"""

from collections import Counter
from dataclasses import dataclass

from pruefstand.core.config import SplitPlan
from pruefstand.core.enums import Split
from pruefstand.core.errors import DatasetError
from pruefstand.core.models.testcase import TestCase
from pruefstand.dataset.splits_pool import Cluster, Pool, Role


@dataclass(frozen=True)
class Candidate:
    """The best base of one cluster with its variants."""

    cluster: Cluster
    base: TestCase
    variants: tuple[TestCase, ...]

    @property
    def types(self) -> frozenset[str]:
        """The perturbation names that apply to the base."""
        return frozenset(v.perturbation for v in self.variants if v.perturbation)

    @property
    def score(self) -> int:
        """Applicability score: how many perturbation names apply to the base."""
        return len(self.types)


def _rank(option: Candidate) -> tuple[int, str]:
    return (-option.score, option.base.id)


def candidates(pool: Pool) -> list[Candidate]:
    """Per perturbed answerable cluster, its best base (highest score, then smaller id), ranked.

    Returns:
        One candidate per cluster, sorted by descending score, then base id.
    """
    found: list[Candidate] = []
    for cluster in pool.select(lambda c: bool(c.variants) and c.role is Role.ANSWERABLE):
        options = [
            Candidate(cluster, b, tuple(v for v in cluster.variants if v.base_id == b.id))
            for b in cluster.plain
        ]
        options = [o for o in options if o.variants]
        if options:
            found.append(min(options, key=_rank))
    return sorted(found, key=_rank)


def _check_types(chosen: list[Candidate], plan: SplitPlan) -> None:
    per_type = Counter(t for o in chosen for t in o.types)
    short = [
        f"{t} ({per_type[t]})"
        for t in plan.robust_pr_types
        if per_type[t] < plan.robust_pr_min_bases_per_type
    ]
    if short:
        msg = (
            f"robust_pr: perturbation types with fewer than {plan.robust_pr_min_bases_per_type} "
            f"bases: {', '.join(short)}"
        )
        raise DatasetError(msg)


def pick_perturbed(pool: Pool, size: int, split: Split, plan: SplitPlan) -> list[TestCase]:
    """Choose ``size`` bases (one per cluster) with their variants for ``split``.

    Args:
        pool: Remaining clusters; the chosen ones are removed.
        size: Bases wanted (0 switches the split off).
        split: ``ROBUST_PR`` (also checks the per-type and perturbed-case quotas) or ``RQ1``.
        plan: The quotas.

    Returns:
        The bases and their variants with ``split`` set; the other cases of the chosen clusters
        are not kept.

    Raises:
        DatasetError: Fewer than ``size`` clusters have a base with variants, a perturbation type
            has too few bases, or too few perturbed cases result (``robust_pr``).
    """
    if size == 0:
        return []
    ranked = candidates(pool)
    if len(ranked) < size:
        msg = f"{split.value}: only {len(ranked)} clusters have a base with variants, need {size}"
        raise DatasetError(msg)
    chosen = ranked[:size]
    if split is Split.ROBUST_PR:
        _check_types(chosen, plan)
        perturbed = sum(len(o.variants) for o in chosen)
        if perturbed < plan.robust_pr_min_perturbed:
            msg = f"robust_pr: {perturbed} perturbed cases < {plan.robust_pr_min_perturbed}"
            raise DatasetError(msg)
    kept: list[TestCase] = []
    for o in chosen:
        used = {o.base.id, *(v.id for v in o.variants)}
        kept += [c.model_copy(update={"split": split}) for c in o.cluster.cases if c.id in used]
    pool.remove(o.cluster for o in chosen)
    return kept
