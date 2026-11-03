"""Quota checks of ``validate_dataset`` against the ``SplitPlan`` defaults (SPEC §3.4).

Rounds: X3.7 (core), P3.1 (full), P3.2 (rq1).

Every finding goes through ``Findings.quota``: a problem on real builds, a logged warning for
``datasets/fixtures/*``.
"""

from collections import Counter, defaultdict
from collections.abc import Sequence

from pruefstand.core.config import NUM_BLOCKS, SplitPlan
from pruefstand.core.enums import Category, Split
from pruefstand.core.models.dataset import DatasetManifest
from pruefstand.core.models.testcase import TestCase
from pruefstand.dataset.io import LoadedDataset
from pruefstand.dataset.splits_pool import ANSWERABLE
from pruefstand.dataset.validate_report import Findings

REQUIRED_SPLITS = (Split.SMOKE, Split.CORE, Split.ROBUST_PR, Split.FULL)


def _clusters_by_tenant(cases: Sequence[TestCase]) -> Counter[str]:
    pairs = {(str(c.tenant), c.cluster_id) for c in cases}
    return Counter(t for t, _ in pairs)


def _smoke(cases: Sequence[TestCase], plan: SplitPlan, out: Findings) -> None:
    if len(cases) < plan.smoke_size:
        out.quota(f"smoke: {len(cases)} cases < {plan.smoke_size}")
    per_category = Counter(c.category for c in cases)
    for category, n in sorted(per_category.items(), key=lambda kv: kv[0].value):
        if n < plan.smoke_min_per_category:
            out.quota(
                f"smoke: category {category.value} has {n} cases < {plan.smoke_min_per_category}"
            )


def _core(cases: Sequence[TestCase], plan: SplitPlan, out: Findings) -> None:
    answerable = [c for c in cases if c.category in ANSWERABLE]
    counts = Counter(c.category for c in cases)
    got = (len(answerable), counts[Category.UNANSWERABLE], counts[Category.INJECTION])
    want = (plan.core_answerable, plan.core_unanswerable, plan.core_injection)
    other = len(cases) - sum(got)
    if got != want or other:
        out.quota(
            f"core: {got[0]} answerable / {got[1]} unanswerable / {got[2]} injection "
            f"(+ {other} other), expected {want[0]} / {want[1]} / {want[2]}"
        )
    clusters = {c.cluster_id for c in answerable}
    if len(clusters) < plan.core_min_answerable_clusters:
        out.quota(
            f"core: {len(clusters)} answerable clusters < {plan.core_min_answerable_clusters}"
        )
    for tenant, n in sorted(_clusters_by_tenant(answerable).items()):
        if n < plan.min_clusters_per_tenant:
            out.quota(
                f"core: tenant {tenant} has {n} answerable clusters "
                f"< {plan.min_clusters_per_tenant}"
            )
    lingual = counts[Category.CROSS_LINGUAL]
    if lingual < plan.core_min_cross_lingual:
        out.quota(f"core: {lingual} cross_lingual cases < {plan.core_min_cross_lingual}")
    subset = [c for c in cases if c.judged_subset]
    if len(subset) != plan.judged_subset_size:
        out.quota(
            f"core: judged_subset has {len(subset)} cases, expected {plan.judged_subset_size}"
        )
    if not any(c.category is Category.INJECTION for c in subset):
        out.quota(
            "core: judged_subset has no injection cases (stratified by category incl. injection)"
        )


def _robust(cases: Sequence[TestCase], plan: SplitPlan, out: Findings) -> None:
    bases = [c for c in cases if c.perturbation is None]
    variants = [c for c in cases if c.perturbation is not None]
    clusters = {c.cluster_id for c in bases}
    if len(clusters) < plan.robust_pr_bases:
        out.quota(f"robust_pr: {len(clusters)} distinct base clusters < {plan.robust_pr_bases}")
    per_type: Counter[str] = Counter()
    for base_id in {v.base_id for v in variants}:
        per_type.update(
            {v.perturbation for v in variants if v.base_id == base_id and v.perturbation}
        )
    for name in plan.robust_pr_types:
        if per_type[name] < plan.robust_pr_min_bases_per_type:
            out.quota(
                f"robust_pr: perturbation {name} has {per_type[name]} bases "
                f"< {plan.robust_pr_min_bases_per_type}"
            )
    if len(variants) < plan.robust_pr_min_perturbed:
        out.quota(f"robust_pr: {len(variants)} perturbed cases < {plan.robust_pr_min_perturbed}")


def _full_block(b: int, cases: Sequence[TestCase], plan: SplitPlan, out: Findings) -> None:
    plain = [c for c in cases if c.perturbation is None]
    variants = [c for c in cases if c.perturbation is not None]
    label = f"full quota: block {b}"
    if len(plain) != plan.full_block_unperturbed:
        out.quota(
            f"{label} has {len(plain)} unperturbed answerable cases, "
            f"expected {plan.full_block_unperturbed}"
        )
    clusters = {c.cluster_id for c in plain}
    if len(clusters) < plan.full_block_min_clusters:
        out.quota(f"{label} has {len(clusters)} clusters < {plan.full_block_min_clusters}")
    for tenant, n in sorted(_clusters_by_tenant(plain).items()):
        if n < plan.min_clusters_per_tenant:
            out.quota(f"{label} tenant {tenant} has {n} clusters < {plan.min_clusters_per_tenant}")
    if len(variants) > plan.full_block_perturbed:
        out.quota(f"{label} has {len(variants)} perturbed variants > {plan.full_block_perturbed}")
    ids = {c.id for c in plain}
    for v in variants:
        if v.base_id not in ids:
            out.quota(f"{label}: variant {v.id!r} has its base {v.base_id!r} outside the block")


def _full(cases: Sequence[TestCase], plan: SplitPlan, out: Findings) -> None:
    refusal = [c for c in cases if c.block is None]
    if not plan.full_refusal_min <= len(refusal) <= plan.full_refusal_max:
        out.quota(
            f"full quota: refusal stratum has {len(refusal)} cases, "
            f"expected {plan.full_refusal_min}-{plan.full_refusal_max}"
        )
    if len({c.cluster_id for c in refusal}) < plan.full_refusal_min_clusters:
        out.quota(
            f"full quota: refusal stratum has {len({c.cluster_id for c in refusal})} clusters "
            f"< {plan.full_refusal_min_clusters}"
        )
    for c in cases:
        if c.category not in ANSWERABLE and c.category is not Category.UNANSWERABLE:
            out.quota(
                f"full quota: case {c.id!r} has category {c.category.value}, not allowed in full"
            )
    by_block: dict[int, list[TestCase]] = defaultdict(list)
    for c in cases:
        if c.block is not None:
            by_block[c.block].append(c)
    for b in range(NUM_BLOCKS):
        _full_block(b, by_block[b], plan, out)
        size = len(by_block[b])
        if len(refusal) + size > plan.nightly_cap:
            out.quota(
                f"nightly block exceeds {plan.nightly_cap} cases "
                f"(refusal {len(refusal)} + block {b} {size})"
            )


def _rq1(cases: Sequence[TestCase], plan: SplitPlan, out: Findings) -> None:
    bases = {c.cluster_id for c in cases if c.perturbation is None}
    if len(bases) < plan.rq1_bases:
        out.quota(f"rq1: {len(bases)} bases < {plan.rq1_bases}")


def check_quotas(loaded: LoadedDataset, manifest: DatasetManifest, out: Findings) -> None:
    """Check the split quotas of ``SplitPlan()`` and report them through ``out.quota``.

    Args:
        loaded: The cases per split.
        manifest: The manifest (decides which splits exist).
        out: Collector.
    """
    plan = SplitPlan()
    for split in REQUIRED_SPLITS:
        if split not in manifest.splits:
            out.quota(f"{split.value}: split is missing from the dataset")
    checks = {
        Split.SMOKE: _smoke,
        Split.CORE: _core,
        Split.ROBUST_PR: _robust,
        Split.FULL: _full,
        Split.RQ1: _rq1,
    }
    for split, check in checks.items():
        if split in loaded.cases:
            check(loaded.cases[split], plan, out)
