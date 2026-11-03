"""``assign_splits``: ``robust_pr`` and ``rq1`` (T4.1, R13 P3.2)."""

from collections import defaultdict

import numpy as np
import pytest
from testsupport.dataset_support import (
    ANSWERABLE,
    answerable_clusters,
    case,
    small_plan,
    with_variants,
)

from pruefstand.core.enums import Split
from pruefstand.core.errors import DatasetError
from pruefstand.core.models.testcase import TestCase
from pruefstand.dataset.splits import assign_splits, assign_splits_report

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


def test_robust_pr_takes_the_applicable_pairs_of_the_best_scoring_bases() -> None:
    cases: list[TestCase] = []
    for i in range(12):
        names = ("typos", "numbers", "dates")[: 1 + i % 3]
        cases += with_variants(case(f"r{i:02d}", f"doc-{i:02d}"), names)
    plan = small_plan(robust_pr_bases=6, robust_pr_types=("typos", "numbers", "dates"))
    report = assign_splits_report(cases, plan, _rng())
    robust = [c for c in report.cases if c.split is Split.ROBUST_PR]
    bases = [c for c in robust if c.perturbation is None]
    assert {b.id for b in bases} == {"r02", "r05", "r08", "r11", "r01", "r04"}
    assert len({b.cluster_id for b in bases}) == 6
    assert len(robust) - len(bases) == 4 * 3 + 2 * 2
    assert report.n_perturbed[Split.ROBUST_PR] == 16


def test_robust_pr_uses_one_base_per_source_document() -> None:
    cases = with_variants(case("x1", "same"), ("typos",)) + with_variants(
        case("x2", "same"), ("typos", "numbers")
    )
    cases += with_variants(case("y1", "other"), ("typos",))
    out = assign_splits(cases, small_plan(robust_pr_bases=2), _rng())
    assert {c.id for c in out if c.perturbation is None} == {"x2", "y1"}


def test_robust_pr_type_below_minimum_names_the_type() -> None:
    cases = [
        c for i in range(6) for c in with_variants(case(f"q{i}", f"d{i}"), ("typos", "numbers"))
    ]
    plan = small_plan(
        robust_pr_bases=6,
        robust_pr_min_bases_per_type=3,
        robust_pr_types=("typos", "numbers", "dates"),
    )
    with pytest.raises(DatasetError, match="dates"):
        assign_splits(cases, plan, _rng())


def test_robust_pr_cluster_shortfall_raises() -> None:
    cases = with_variants(case("s1", "d1"), ("typos",))
    with pytest.raises(DatasetError, match="robust_pr"):
        assign_splits(cases, small_plan(robust_pr_bases=2), _rng())


def test_rq1_is_cluster_disjoint_and_has_no_block_or_subset() -> None:
    cases = _perturbed_bases(60, 60, ("typos", "numbers")) + answerable_clusters(30)
    plan = small_plan(robust_pr_bases=10, rq1_bases=30, core_answerable=10)
    out = assign_splits(cases, plan, _rng())
    rq1 = [c for c in out if c.split is Split.RQ1]
    assert len({c.cluster_id for c in rq1 if c.perturbation is None}) == 30
    assert len(rq1) == 30 * 3
    assert all(c.block is None and not c.judged_subset for c in rq1)
    assert all(len(s) == 1 for s in _by_cluster(out).values())
