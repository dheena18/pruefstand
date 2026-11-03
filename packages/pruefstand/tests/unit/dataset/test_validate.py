"""``validate_dataset``: structure, licences, clusters, quotas, blocks, ``rq1`` (T4.1 S3)."""

import logging
import shutil
from pathlib import Path

import pytest
from testsupport.dataset_support import ANSWERABLE, case, edit, has, problems_for, write_dir

from pruefstand.core.enums import Category, Split
from pruefstand.core.models.testcase import TestCase
from pruefstand.dataset.validate import validate_dataset

ROOT = Path(__file__).resolve().parents[5]
SLICE = ROOT / "datasets/fixtures/slice_v1"


def test_a_complete_release_build_is_valid(tmp_path: Path, release: list[TestCase]) -> None:
    assert problems_for(tmp_path, release) == []


def test_the_slice_fixture_is_valid_and_logs_quota_warnings(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        assert validate_dataset(SLICE) == []
    assert "core" in caplog.text


# --- structure ------------------------------------------------------------------------------


def _small(tmp_path: Path, cases: list[TestCase]) -> list[str]:
    return problems_for(tmp_path, cases)


def test_duplicate_id_names_the_id(tmp_path: Path) -> None:
    a = case("dup", "d1", split=Split.CORE)
    b = case("dup", "d2", split=Split.SMOKE)
    assert has(_small(tmp_path, [a, b]), "duplicate", "dup")


def test_cluster_spread_over_splits_is_named(tmp_path: Path) -> None:
    cases = [
        case("a", "gii-bgb-622", split=Split.SMOKE),
        case("a~typos", "gii-bgb-622", split=Split.CORE, perturbation="typos", base_id="a"),
    ]
    assert has(_small(tmp_path, cases), "cluster gii-bgb-622 spans", "core", "smoke")


def test_schema_error_names_file_and_line(tmp_path: Path) -> None:
    directory = write_dir(
        tmp_path / "d", [case(f"c{i}", f"d{i}", split=Split.CORE) for i in range(8)]
    )
    lines = (directory / "core.jsonl").read_text(encoding="utf-8").splitlines()
    lines[6] = '{"id": "broken"}'
    (directory / "core.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert has(validate_dataset(directory), "core.jsonl:7")


def test_injection_without_marker_is_a_problem(tmp_path: Path) -> None:
    bad = case("i1", "d1", category=Category.INJECTION, split=Split.CORE)
    directory = write_dir(tmp_path / "d", [bad])
    text = (directory / "core.jsonl").read_text(encoding="utf-8")
    text = text.replace('"injection_marker": "PWNED-3f9a"', '"injection_marker": null')
    (directory / "core.jsonl").write_text(text, encoding="utf-8")
    assert has(validate_dataset(directory), "core.jsonl:1", "injection_marker")


def test_unknown_license_config_is_a_problem(tmp_path: Path) -> None:
    cases = [case("a", "d1", split=Split.CORE, license_config="cc0")]
    assert has(_small(tmp_path, cases), "license_config", "cc0")


def test_cluster_mixing_germanquad_and_oldp_is_a_problem(tmp_path: Path) -> None:
    cases = [
        case("a", "d1", split=Split.CORE, license_config="germanquad_derived"),
        case("b", "d1", split=Split.CORE, license_config="oldp_derived"),
    ]
    assert has(_small(tmp_path, cases), "d1", "germanquad_derived", "oldp_derived")


def test_corpus_version_mismatch_with_the_manifest(tmp_path: Path) -> None:
    cases = [case("a", "d1", split=Split.CORE, corpus_version="other")]
    directory = write_dir(tmp_path / "d", cases)
    assert has(validate_dataset(directory), "corpus_version")


def test_manifest_counts_must_equal_the_rows(tmp_path: Path) -> None:
    cases = [case("a", "d1", split=Split.CORE)]
    problems = problems_for(tmp_path, cases, splits={Split.CORE: 5})
    assert has(problems, "core", "5", "1")


def test_robust_pr_case_without_perturbation_must_be_a_base(tmp_path: Path) -> None:
    cases = [case("lonely", "d1", split=Split.ROBUST_PR)]
    assert has(_small(tmp_path, cases), "lonely", "perturbation")


# --- quotas (release builds are strict, fixtures only warn) -----------------------------------


def test_core_with_199_answerable_clusters(tmp_path: Path, release: list[TestCase]) -> None:
    ans = [c for c in release if c.split is Split.CORE and c.category in ANSWERABLE]
    merge = {c.id for c in ans[1:22]}
    cases = edit(release, lambda c: c.id in merge, cluster_id=ans[0].cluster_id)
    assert has(problems_for(tmp_path, cases), "core: 199 answerable clusters < 200")


def test_core_tenant_with_29_answerable_clusters(tmp_path: Path, release: list[TestCase]) -> None:
    mine = [
        c
        for c in release
        if c.split is Split.CORE and c.tenant == "t1" and c.category in ANSWERABLE
    ]
    moved = {c.id for c in mine[29:]}
    cases = edit(release, lambda c: c.id in moved, tenant="t0")
    assert has(problems_for(tmp_path, cases), "core", "t1", "29")


def test_core_category_counts_221_49_30(tmp_path: Path, release: list[TestCase]) -> None:
    victim = next(
        c for c in release if c.split is Split.CORE and c.category is Category.UNANSWERABLE
    )
    cases = edit(
        release, lambda c: c.id == victim.id, category=Category.FACTUAL, expect_refusal=False
    )
    assert has(problems_for(tmp_path, cases), "core", "221", "49", "30")


def test_the_same_finding_under_fixtures_is_only_a_warning(
    tmp_path: Path, release: list[TestCase], caplog: pytest.LogCaptureFixture
) -> None:
    victim = next(
        c for c in release if c.split is Split.CORE and c.category is Category.UNANSWERABLE
    )
    cases = edit(
        release, lambda c: c.id == victim.id, category=Category.FACTUAL, expect_refusal=False
    )
    directory = write_dir(tmp_path / "datasets" / "fixtures" / "x", cases)
    with caplog.at_level(logging.WARNING):
        assert validate_dataset(directory) == []
    assert "221" in caplog.text


def test_full_with_99_unanswerable(tmp_path: Path, release: list[TestCase]) -> None:
    refusal = [c for c in release if c.split is Split.FULL and c.category is Category.UNANSWERABLE]
    drop = {c.id for c in refusal[99:]}
    problems = problems_for(tmp_path, [c for c in release if c.id not in drop])
    assert has(problems, "full", "99")


def test_refusal_stratum_of_130(tmp_path: Path, release: list[TestCase]) -> None:
    refusal = [c for c in release if c.split is Split.FULL and c.category is Category.UNANSWERABLE]
    drop = {c.id for c in refusal[130:]}
    assert has(problems_for(tmp_path, [c for c in release if c.id not in drop]), "refusal", "130")


def test_robust_pr_with_299_perturbed_cases(tmp_path: Path, release: list[TestCase]) -> None:
    variants = [c for c in release if c.split is Split.ROBUST_PR and c.perturbation]
    drop = {c.id for c in variants[299:]}
    assert has(problems_for(tmp_path, [c for c in release if c.id not in drop]), "299", "perturbed")


def test_robust_pr_with_39_base_clusters(tmp_path: Path, release: list[TestCase]) -> None:
    base = next(c for c in release if c.split is Split.ROBUST_PR and c.perturbation is None)
    drop = {c.id for c in release if c.base_id == base.id}
    assert has(problems_for(tmp_path, [c for c in release if c.id not in drop]), "39", "robust_pr")


def test_fixture_copy_is_not_modified_by_validation(tmp_path: Path) -> None:
    copy = tmp_path / "datasets" / "fixtures" / "slice_v1"
    shutil.copytree(SLICE, copy)
    before = sorted(p.name for p in copy.iterdir())
    validate_dataset(copy)
    assert sorted(p.name for p in copy.iterdir()) == before
