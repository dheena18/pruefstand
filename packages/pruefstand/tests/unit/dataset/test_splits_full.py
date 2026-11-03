"""``assign_splits``: nightly blocks, the ``full`` quota and the judged subset (T4.1, R12/R13)."""

from collections import Counter, defaultdict

import numpy as np
import pytest
from testsupport.dataset_support import (
    ANSWERABLE,
    answerable_clusters,
    case,
    role_cases,
    small_plan,
    with_variants,
)

from pruefstand.core.enums import Category, Split
from pruefstand.core.errors import DatasetError
from pruefstand.core.models.testcase import TestCase
from pruefstand.dataset.splits import assign_splits, assign_splits_report, assignment_summary

TENANTS = ("t0", "t1", "t2")


def _rng(seed: int = 1) -> np.random.Generator:
    return np.random.default_rng(seed)


def _full_fixture() -> list[TestCase]:
    return answerable_clusters(90, tenants=TENANTS) + role_cases(
        Category.UNANSWERABLE, 20, tenants=TENANTS, prefix="u"
    )


FULL_PLAN = {"full_refusal": 20, "full_block_unperturbed": 30, "full_refusal_min": 0}


def test_blocks_are_assigned_per_stratum_and_refusal_has_none() -> None:
    out = assign_splits(_full_fixture(), small_plan(**FULL_PLAN), _rng())
    assert all(c.split is Split.FULL for c in out)
    refusal = [c for c in out if c.category is Category.UNANSWERABLE]
    assert len(refusal) == 20
    assert all(c.block is None for c in refusal)
    rest = [c for c in out if c.category is not Category.UNANSWERABLE]
    assert {c.block for c in rest} == {0, 1, 2}
    per_block = Counter(c.block for c in rest)
    assert per_block == {0: 30, 1: 30, 2: 30}
    strata: dict[tuple[str, Category], Counter[int | None]] = defaultdict(Counter)
    for c in rest:
        strata[(c.tenant, c.category)][c.block] += 1
    for counts in strata.values():
        values = [counts[b] for b in (0, 1, 2)]
        assert max(values) - min(values) <= 1


def test_blocks_same_seed_same_blocks_and_summary_matches() -> None:
    plan = small_plan(**FULL_PLAN)
    first = assign_splits(_full_fixture(), plan, _rng(3))
    assert first == assign_splits(_full_fixture(), plan, _rng(3))
    blocks, subset, seed = assignment_summary(first, 3)
    assert blocks == {"refusal": 20, "0": 30, "1": 30, "2": 30}
    assert (subset, seed) == (0, 3)


def test_cases_outside_full_have_no_block() -> None:
    cases = _full_fixture() + answerable_clusters(10, prefix="z")
    out = assign_splits(cases, small_plan(core_answerable=10, **FULL_PLAN), _rng())
    assert all(c.block is None for c in out if c.split is Split.CORE)


def test_full_quota_with_surplus_drops_and_counts_the_rest() -> None:
    bases = answerable_clusters(1100, tenants=TENANTS, prefix="f")
    perturbed = [
        c
        for i in range(120)
        for c in with_variants(
            case(f"p{i:03d}", f"p-doc-{i:03d}", tenant=TENANTS[i % 3]),
            ("typos", "numbers", "dates"),
        )
    ]
    refusal = role_cases(Category.UNANSWERABLE, 200, tenants=TENANTS, prefix="u")
    plan = small_plan(full_refusal=150, full_block_unperturbed=300, full_block_perturbed=150)
    report = assign_splits_report(bases + perturbed + refusal, plan, _rng())
    out = list(report.cases)
    assert sum(1 for c in out if c.block is None) == 150
    for b in (0, 1, 2):
        in_block = [c for c in out if c.block == b]
        plain = [c for c in in_block if c.perturbation is None]
        variants = [c for c in in_block if c.perturbation is not None]
        assert len(plain) == 300
        assert len({c.cluster_id for c in plain}) >= 250
        assert len(variants) <= 150
        ids = {c.id for c in plain}
        assert all(v.base_id in ids for v in variants)
        assert all(sum(1 for c in plain if c.tenant == t) >= 30 for t in TENANTS)
    clusters_blocks: dict[str, set[int | None]] = defaultdict(set)
    for c in out:
        clusters_blocks[c.cluster_id].add(c.block)
    assert all(len(v) == 1 for v in clusters_blocks.values())
    assert len(report.dropped) + len(out) == 1100 + 480 + 200


def test_block_shortfall_raises() -> None:
    with pytest.raises(DatasetError, match="full"):
        assign_splits(answerable_clusters(50), small_plan(full_block_unperturbed=30), _rng())


# --- judged subset --------------------------------------------------------------------------


def test_judged_subset_is_stratified_and_includes_injection() -> None:
    cases = (
        answerable_clusters(300, tenants=TENANTS)
        + role_cases(Category.UNANSWERABLE, 60, tenants=TENANTS, prefix="u")
        + role_cases(Category.INJECTION, 40, tenants=TENANTS, prefix="i")
    )
    plan = small_plan(
        core_answerable=220, core_unanswerable=50, core_injection=30, judged_subset_size=150
    )
    first = assign_splits(cases, plan, _rng(2))
    assert first == assign_splits(cases, plan, _rng(2))
    subset = [c for c in first if c.judged_subset]
    assert len(subset) == 150
    assert all(c.split is Split.CORE for c in subset)
    groups = Counter("ans" if c.category in ANSWERABLE else c.category.value for c in subset)
    for key, want in {"ans": 110, "unanswerable": 25, "injection": 15}.items():
        assert abs(groups[key] - want) <= 1
    core = [c for c in first if c.split is Split.CORE]
    for key in groups:
        in_core = [
            c for c in core if ("ans" if c.category in ANSWERABLE else c.category.value) == key
        ]
        in_sub = [
            c for c in subset if ("ans" if c.category in ANSWERABLE else c.category.value) == key
        ]
        for t in TENANTS:
            share = len(in_sub) * sum(1 for c in in_core if c.tenant == t) / len(in_core)
            assert abs(sum(1 for c in in_sub if c.tenant == t) - share) <= 1
    assert assignment_summary(first, 2)[1] == 150
    assert not any(c.judged_subset for c in first if c.split is not Split.CORE)
