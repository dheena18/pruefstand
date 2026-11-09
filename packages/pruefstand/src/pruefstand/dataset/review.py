"""Model-review bookkeeping: the review sample, decisions, error rates (T4.7a, SPEC §3.5 steps 4-5).

The model verdicts themselves come from ``dataset.model_review``; this module holds the rules
that turn them into dataset changes. A ``reject`` removes the case **and its whole cluster** from
every split (a cluster is one source document; keeping part of it would break the cluster-disjoint
splits). The reviewer is reject-only (round 9 X3.8, ADR-0019): its ``fix`` may change the question
and never the reference answer, so a ``fix`` that carries a ``fixed_answer`` becomes a ``reject``.

``select_smoke``, ``sample_spotcheck`` and ``spotcheck_trust`` live in ``review_select`` and are
re-exported here.
"""

import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np

from pruefstand.core.enums import Category, Split
from pruefstand.core.models.dataset import ReviewItem, ReviewRound
from pruefstand.core.models.testcase import TestCase
from pruefstand.dataset.review_rates import (
    REWRITE_FORBIDDEN,
    StratumRate,
    error_rates,
    normalise_item,
    reviewed_items,
    rounds_of,
)
from pruefstand.dataset.review_select import sample_spotcheck, select_smoke, spotcheck_trust

__all__ = [
    "ATTACK_CATEGORIES",
    "MODEL_REVIEWED_SOURCE",
    "REWRITE_FORBIDDEN",
    "ApplyResult",
    "StratumRate",
    "apply_decisions",
    "error_rates",
    "normalise_item",
    "sample_for_review",
    "sample_spotcheck",
    "sampled_part",
    "select_smoke",
    "spotcheck_trust",
    "stratum_of",
]

ATTACK_CATEGORIES = frozenset(
    {
        Category.INJECTION,
        Category.LEAK_PROBE,
        Category.SYSTEM_PROMPT_EXTRACTION,
        Category.FILTER_BYPASS,
    }
)
MODEL_REVIEWED_SOURCE = "generated+model-reviewed"
_ALWAYS = frozenset({Split.SMOKE, Split.CORE})


def stratum_of(case: TestCase) -> str:
    """Return the review stratum of ``case``: ``<category>/<generation prompt version>``."""
    return f"{case.category.value}/{case.generation_prompt_version or 'none'}"


def sampled_part(cases: Sequence[TestCase]) -> list[TestCase]:
    """Return the sampled part: every case except smoke, core and attack or probe cases."""
    return [c for c in cases if c.split not in _ALWAYS and c.category not in ATTACK_CATEGORIES]


def _share(n: int, fraction: float) -> int:
    return math.ceil(round(n * fraction, 9))


def sample_for_review(
    cases: Sequence[TestCase],
    *,
    seed: int,
    full_fraction: float = 0.2,
    min_per_category: int = 30,
) -> list[TestCase]:
    """Choose the cases the model reviews (round-8 W3.13).

    Every ``smoke`` and ``core`` case and every attack or probe case (any split) is taken. Of the
    rest (``full``, ``robust_pr``, ``rq1``) a seeded ``full_fraction`` per stratum (category x
    generation prompt version, rounded up) is drawn, then every category is topped up to
    ``min_per_category`` where it has that many cases.

    Args:
        cases: The assigned cases.
        seed: Seed of the draw; the same seed and input give the same sample.
        full_fraction: Share per stratum of the sampled part.
        min_per_category: Smallest number per category of the sampled part.

    Returns:
        The chosen cases in input order.

    Examples:
        >>> sample_for_review([], seed=1)
        []
    """
    rng = np.random.default_rng(seed)
    pool = sampled_part(cases)
    strata: dict[str, list[TestCase]] = defaultdict(list)
    for case in sorted(pool, key=lambda c: c.id):
        strata[stratum_of(case)].append(case)
    chosen: set[str] = set()
    for key in sorted(strata):
        members = strata[key]
        order = rng.permutation(len(members))
        chosen |= {members[int(i)].id for i in order[: _share(len(members), full_fraction)]}
    by_category: dict[Category, list[TestCase]] = defaultdict(list)
    for case in sorted(pool, key=lambda c: c.id):
        by_category[case.category].append(case)
    for category in sorted(by_category, key=lambda c: c.value):
        members = by_category[category]
        short = min(min_per_category, len(members)) - sum(1 for c in members if c.id in chosen)
        spare = [
            members[int(i)]
            for i in rng.permutation(len(members))
            if members[int(i)].id not in chosen
        ]
        chosen |= {c.id for c in spare[: max(short, 0)]}
    always = {c.id for c in cases if c.split in _ALWAYS or c.category in ATTACK_CATEGORIES}
    keep = chosen | always
    return [c for c in cases if c.id in keep]


@dataclass(frozen=True)
class ApplyResult:
    """What ``apply_decisions`` did.

    Attributes:
        cases: The kept cases (input order), fixes applied.
        rejected: Ids removed by a reject, cluster mates included.
        fixed: Ids whose question (and answer) was replaced.
        variants_dropped: Perturbed variants removed because their base question was fixed.
        reasons: Why each rejected reviewed case was rejected (first reason).
        rounds: The new ``ReviewRound`` entries, one per generation prompt version.
        needs_regeneration: Strata above the error threshold.
    """

    cases: tuple[TestCase, ...]
    rejected: tuple[str, ...]
    fixed: tuple[str, ...]
    variants_dropped: tuple[str, ...]
    reasons: dict[str, str]
    rounds: tuple[ReviewRound, ...]
    needs_regeneration: tuple[str, ...]


def _change_set(
    cases: Sequence[TestCase], by_id: dict[str, ReviewItem]
) -> tuple[list[TestCase], set[str], set[str], set[str]]:
    """Return the kept cases (fixes applied) and the sets of cluster ids, fixed ids, stale ids."""
    clusters: dict[str, str] = {c.id: c.cluster_id for c in cases}
    dead = {clusters.get(i.case_id, i.cluster_id) for i in by_id.values() if i.verdict == "reject"}
    kept = [c for c in cases if c.cluster_id not in dead]
    fixed = {i.case_id for i in by_id.values() if i.verdict == "fix"} & {c.id for c in kept}
    stale = {str(c.id) for c in kept if c.perturbation and c.base_id in fixed and c.id not in fixed}
    out = [_fixed(c, by_id[c.id]) if c.id in fixed else c for c in kept if c.id not in stale]
    return out, dead, fixed, stale


def apply_decisions(
    cases: Sequence[TestCase],
    items: Sequence[ReviewItem],
    *,
    reviewer: str,
    today: date,
    existing: Sequence[ReviewRound] = (),
    threshold: float = 0.10,
    reject_only: bool = True,
) -> ApplyResult:
    """Turn review results into dataset changes and ``ReviewRound`` entries.

    A ``reject`` removes the case and every case of its cluster. A ``fix`` replaces the question
    (and, only for a reviewer that may rewrite references, the answer) and sets
    ``source="generated+model-reviewed"``; perturbed variants of a fixed base are dropped, their
    text was derived from the old question.

    Args:
        cases: The cases of the dataset.
        items: Review results (see ``dataset.model_review``).
        reviewer: ``model:<id>@<review prompt>`` for the new rounds.
        today: Date of the rounds.
        existing: Rounds already in the manifest (numbering continues after them).
        threshold: Error rate above which a stratum needs regeneration.
        reject_only: The reviewer must not rewrite references (ADR-0019).

    Returns:
        The ``ApplyResult``.
    """
    by_id = {i.case_id: i for i in (normalise_item(i, reject_only=reject_only) for i in items)}
    out, dead, fixed, stale = _change_set(cases, by_id)
    rates = error_rates(items, threshold=threshold, reject_only=reject_only)
    return ApplyResult(
        cases=tuple(out),
        rejected=tuple(sorted(c.id for c in cases if c.cluster_id in dead)),
        fixed=tuple(sorted(fixed)),
        variants_dropped=tuple(sorted(stale)),
        reasons={
            i.case_id: i.reasons[0] if i.reasons else "model_reject"
            for i in by_id.values()
            if i.verdict == "reject"
        },
        rounds=rounds_of(
            reviewed_items(items, reject_only=reject_only), reviewer, today, len(existing) + 1
        ),
        needs_regeneration=tuple(k for k, r in rates.items() if r.needs_regeneration),
    )


def _fixed(case: TestCase, item: ReviewItem) -> TestCase:
    changes: dict[str, object] = {"source": MODEL_REVIEWED_SOURCE}
    if item.fixed_question:
        changes["question"] = item.fixed_question
    if item.fixed_answer:
        changes["reference_answer"] = item.fixed_answer
    return case.model_copy(update=changes)
