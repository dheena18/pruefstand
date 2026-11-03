"""``validate_dataset``: blocks, judged subset, ``full`` and ``rq1`` quotas (T4.1 S3, R12/R13)."""

from pathlib import Path

from testsupport.dataset_support import edit, has, problems_for

from pruefstand.core.enums import Category, Split
from pruefstand.core.models.testcase import TestCase


def _full_plain(release: list[TestCase], block: int) -> list[TestCase]:
    return [c for c in release if c.split is Split.FULL and c.block == block and not c.perturbation]


def test_full_case_without_block_is_named(tmp_path: Path, release: list[TestCase]) -> None:
    victim = _full_plain(release, 0)[0]
    cases = edit(release, lambda c: c.id == victim.id, block=None)
    assert has(problems_for(tmp_path, cases), victim.id, "block")


def test_block_three_is_a_schema_problem(tmp_path: Path, release: list[TestCase]) -> None:
    victim = _full_plain(release, 0)[0]
    cases = edit(release, lambda c: c.id == victim.id, block=3)
    assert has(problems_for(tmp_path, cases), "full.jsonl:", "block")


def test_block_on_a_core_case_is_a_problem(tmp_path: Path, release: list[TestCase]) -> None:
    victim = next(c for c in release if c.split is Split.CORE)
    cases = edit(release, lambda c: c.id == victim.id, block=1)
    assert has(problems_for(tmp_path, cases), "core.jsonl:", "block")


def test_cluster_in_two_blocks(tmp_path: Path, release: list[TestCase]) -> None:
    variant = next(c for c in release if c.split is Split.FULL and c.perturbation and c.block == 0)
    cases = edit(release, lambda c: c.id == variant.id, block=1)
    assert has(problems_for(tmp_path, cases), variant.cluster_id, "blocks")


def test_judged_subset_on_a_full_case_is_a_problem(tmp_path: Path, release: list[TestCase]) -> None:
    victim = _full_plain(release, 0)[0]
    cases = edit(release, lambda c: c.id == victim.id, judged_subset=True)
    assert has(problems_for(tmp_path, cases), "full.jsonl:", "judged_subset")


def test_nightly_block_exceeding_600_cases(tmp_path: Path, release: list[TestCase]) -> None:
    moved = _full_plain(release, 1)[0]
    cases = edit(release, lambda c: c.id == moved.id, block=0)
    assert has(problems_for(tmp_path, cases), "nightly block exceeds 600 cases")


def test_149_judged_subset_cases(tmp_path: Path, release: list[TestCase]) -> None:
    victim = next(c for c in release if c.judged_subset)
    cases = edit(release, lambda c: c.id == victim.id, judged_subset=False)
    assert has(problems_for(tmp_path, cases), "judged_subset", "149")


def test_judged_subset_without_injection(tmp_path: Path, release: list[TestCase]) -> None:
    cases = edit(
        release, lambda c: c.judged_subset and c.category is Category.INJECTION, judged_subset=False
    )
    assert has(problems_for(tmp_path, cases), "injection")


def test_block_with_299_unperturbed_answerable_cases(
    tmp_path: Path, release: list[TestCase]
) -> None:
    keep_bases = {c.base_id for c in release if c.perturbation}
    victim = next(c for c in _full_plain(release, 0) if c.id not in keep_bases)
    problems = problems_for(tmp_path, [c for c in release if c.id != victim.id])
    assert has(problems, "full quota", "block 0", "299")


def test_block_with_249_clusters(tmp_path: Path, release: list[TestCase]) -> None:
    keep_bases = {c.base_id for c in release if c.perturbation}
    merge = {c.id for c in _full_plain(release, 0) if c.id not in keep_bases}
    merge = set(sorted(merge)[:52])
    cases = edit(release, lambda c: c.id in merge, cluster_id="merged")
    assert has(problems_for(tmp_path, cases), "full quota", "block 0", "249")


def test_block_tenant_with_29_clusters(tmp_path: Path, release: list[TestCase]) -> None:
    mine = [c for c in _full_plain(release, 0) if c.tenant == "t2"]
    moved = {c.id for c in mine[29:]}
    cases = edit(release, lambda c: c.id in moved, tenant="t0")
    assert has(problems_for(tmp_path, cases), "full quota", "block 0", "t2", "29")


def test_block_with_151_perturbed_variants(tmp_path: Path, release: list[TestCase]) -> None:
    variant = next(c for c in release if c.split is Split.FULL and c.perturbation and c.block == 0)
    extra = variant.model_copy(update={"id": variant.id + "-extra"})
    assert has(problems_for(tmp_path, [*release, extra]), "full quota", "block 0", "151")


def test_variant_whose_base_sits_in_another_block(tmp_path: Path, release: list[TestCase]) -> None:
    variant = next(c for c in release if c.split is Split.FULL and c.perturbation and c.block == 0)
    base = next(c for c in release if c.id == variant.base_id)
    cases = edit(release, lambda c: c.id == base.id, block=1)
    assert has(problems_for(tmp_path, cases), "full quota", "base")


def test_rq1_cluster_shared_with_full(tmp_path: Path, release: list[TestCase]) -> None:
    rq1 = next(c for c in release if c.split is Split.RQ1)
    full = next(c for c in release if c.split is Split.FULL and c.perturbation is None)
    cases = edit(release, lambda c: c.id == rq1.id, cluster_id=full.cluster_id)
    assert has(problems_for(tmp_path, cases), "rq1", full.cluster_id)


def test_rq1_with_fewer_than_300_bases(tmp_path: Path, release: list[TestCase]) -> None:
    base = next(c for c in release if c.split is Split.RQ1 and c.perturbation is None)
    drop = {c.id for c in release if c.base_id == base.id}
    assert has(problems_for(tmp_path, [c for c in release if c.id not in drop]), "rq1", "299")


def test_manifest_blocks_must_equal_the_rows(tmp_path: Path, release: list[TestCase]) -> None:
    problems = problems_for(tmp_path, release, blocks={"refusal": 150, "0": 1, "1": 1, "2": 1})
    assert has(problems, "blocks")
