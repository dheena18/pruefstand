"""``assign_splits``: whole clusters, quotas, nightly blocks, judged subset, ``rq1`` (T4.1 S2)."""

import logging
from collections import Counter, defaultdict

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
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
from pruefstand.dataset.splits import (
    assign_splits,
    assign_splits_report,
)

TENANTS = ("t0", "t1", "t2")


def _rng(seed: int = 1) -> np.random.Generator:
    return np.random.default_rng(seed)


def _by_cluster(cases: list[TestCase]) -> dict[str, set[Split]]:
    out: dict[str, set[Split]] = defaultdict(set)
    for c in cases:
        out[c.cluster_id].add(c.split)
    return out


def _perturbed_bases(n: int, docs: int, names: tuple[str, ...]) -> list[TestCase]:
    out: list[TestCase] = []
    for i in range(n):
        base = case(
            f"b{i:03d}",
            f"doc-{i % docs:02d}",
            category=ANSWERABLE[i % 4],
            tenant=TENANTS[(i % docs) % 3],
        )
        out += with_variants(base, names)
    return out


# --- clusters stay together ---------------------------------------------------------------


def test_every_cluster_lands_in_exactly_one_split_and_smoke_has_three_per_category() -> None:
    cases = _perturbed_bases(100, 40, ("typos", "numbers", "dates"))
    plan = small_plan(smoke_size=24, smoke_min_per_category=3, core_answerable=30)
    out = assign_splits(cases, plan, _rng())
    assert all(len(s) == 1 for s in _by_cluster(out).values())
    smoke = Counter(c.category for c in out if c.split is Split.SMOKE)
    assert all(smoke[cat] >= 3 for cat in ANSWERABLE)
    assert not any(c.perturbation for c in out if c.split in {Split.SMOKE, Split.CORE})


def test_same_seed_same_assignment_other_seed_differs() -> None:
    cases = answerable_clusters(60, tenants=TENANTS)
    plan = small_plan(smoke_size=10, core_answerable=20)
    first = assign_splits(cases, plan, _rng(5))
    assert first == assign_splits(cases, plan, _rng(5))
    assert first != assign_splits(cases, plan, _rng(6))


def test_two_base_questions_of_one_source_doc_share_a_split() -> None:
    cases = answerable_clusters(40, per_cluster=2)
    out = assign_splits(cases, small_plan(smoke_size=8, core_answerable=20), _rng())
    assert {s for c in out if c.cluster_id == "a-doc-0003" for s in [c.split]} <= {
        Split.SMOKE,
        Split.CORE,
    }
    assert all(len(s) == 1 for s in _by_cluster(out).values())


def test_core_composition_and_exact_counts() -> None:
    cases = (
        answerable_clusters(300, tenants=TENANTS)
        + role_cases(Category.UNANSWERABLE, 80, tenants=TENANTS, prefix="u")
        + role_cases(Category.INJECTION, 40, tenants=TENANTS, prefix="i")
    )
    plan = small_plan(core_answerable=220, core_unanswerable=50, core_injection=30)
    out = assign_splits(cases, plan, _rng())
    core = [c for c in out if c.split is Split.CORE]
    roles = Counter("ans" if c.category in ANSWERABLE else c.category.value for c in core)
    assert roles == {"ans": 220, "unanswerable": 50, "injection": 30}
    assert sum(1 for c in core if c.category is Category.CROSS_LINGUAL) >= 30


def test_shortfall_raises_dataset_error() -> None:
    with pytest.raises(DatasetError, match="core"):
        assign_splits(answerable_clusters(10), small_plan(core_answerable=20), _rng())


def test_mixed_role_cluster_is_dropped_and_counted() -> None:
    mixed = [
        case("m1", "mix"),
        case("m2", "mix", category=Category.UNANSWERABLE),
    ]
    report = assign_splits_report(
        mixed + answerable_clusters(5), small_plan(core_answerable=5), _rng()
    )
    assert {c.id for c in report.dropped} == {"m1", "m2"}
    assert report.reasons["mixed_role"] == 2
    assert sum(report.reasons.values()) == len(report.dropped)


def test_every_drop_reason_is_reported_and_logged(caplog: pytest.LogCaptureFixture) -> None:
    surplus = answerable_clusters(10, prefix="s")
    trimmed = [case(f"t{j}", "tr-doc") for j in range(3)]
    variants = with_variants(case("v0", "v-doc"), ("typos", "numbers"))
    plan = small_plan(core_answerable=4)
    with caplog.at_level(logging.WARNING):
        report = assign_splits_report(surplus + trimmed + variants, plan, _rng(0))
    assert sum(report.reasons.values()) == len(report.dropped) > 0
    assert set(report.reasons) <= {"surplus", "mixed_role", "trimmed", "variants_dropped"}
    assert "splits_dropped" in caplog.text


@given(sizes=st.lists(st.integers(1, 4), min_size=3, max_size=30), seed=st.integers(0, 50))
@settings(max_examples=300, deadline=None)
def test_no_cluster_spans_two_splits_and_the_total_is_preserved(
    sizes: list[int], seed: int
) -> None:
    cases = [
        case(f"c{i}-{j}", f"doc-{i}", category=ANSWERABLE[j % 4])
        for i, size in enumerate(sizes)
        for j in range(size)
    ]
    plan = small_plan(smoke_size=len(cases) // 8, core_answerable=len(cases) // 8)
    report = assign_splits_report(cases, plan, _rng(seed))
    assert all(len(s) == 1 for s in _by_cluster(list(report.cases)).values())
    assert len(report.cases) + len(report.dropped) == len(cases)


def test_smoke_minimum_larger_than_the_size_is_trimmed_not_an_error() -> None:
    cases = answerable_clusters(20)
    out = assign_splits(cases, small_plan(smoke_size=6, smoke_min_per_category=3), _rng())
    assert sum(1 for c in out if c.split is Split.SMOKE) == 6
