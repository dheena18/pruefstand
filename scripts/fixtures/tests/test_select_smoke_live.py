"""The `smoke_live` selection rule (T1.11 S1b): quotas, determinism, errors, `--check`."""

import json
from collections import Counter
from pathlib import Path

import pytest
from fixtures import select_smoke_live as sel

from pruefstand.core.enums import Category, Split
from pruefstand.core.models.testcase import TestCase

SOURCE = sel.SOURCE


@pytest.fixture(scope="module")
def source() -> list[TestCase]:
    return sel.load_source(SOURCE)


def _ids(cases: list[TestCase]) -> set[str]:
    return {c.id for c in cases}


def test_the_source_has_the_40_cases_of_the_prompt(source: list[TestCase]) -> None:
    counts = Counter(c.category for c in source)
    assert len(source) == 40
    assert counts == {
        Category.FACTUAL: 14,
        Category.MULTI_HOP: 4,
        Category.COMPARISON: 2,
        Category.UNANSWERABLE: 5,
        Category.CROSS_LINGUAL: 4,
        Category.INJECTION: 4,
        Category.LEAK_PROBE: 4,
        Category.SYSTEM_PROMPT_EXTRACTION: 2,
        Category.FILTER_BYPASS: 1,
    }


def test_smoke_live_has_20_cases_and_smoke_the_other_20(source: list[TestCase]) -> None:
    live, rest = sel.select(source)
    assert len(live) == len(rest) == 20
    assert _ids(live).isdisjoint(_ids(rest))
    assert _ids(live) | _ids(rest) == _ids(source)
    assert {c.split for c in live} == {Split.SMOKE_LIVE}
    assert {c.split for c in rest} == {Split.SMOKE}


def test_the_quotas_of_the_rule(source: list[TestCase]) -> None:
    live, _ = sel.select(source)
    counts = Counter(c.category for c in live)
    assert counts[Category.UNANSWERABLE] == 2
    assert counts[Category.INJECTION] == 2
    assert counts[Category.SYSTEM_PROMPT_EXTRACTION] == 1
    probes = {c.tenant for c in live if c.category is Category.LEAK_PROBE}
    assert {"kanzlei_mueller", "stadtwerke_sued"} <= probes
    others = [
        c
        for c in live
        if c.category not in {Category.LEAK_PROBE, Category.UNANSWERABLE, Category.INJECTION}
        and c.category is not Category.SYSTEM_PROMPT_EXTRACTION
    ]
    assert others
    assert all(c.category is Category.FACTUAL and c.gold_citations for c in others)
    assert sum(c.lang.value == "en" for c in others) >= 2


def test_lowest_ids_come_first_within_a_quota(source: list[TestCase]) -> None:
    live, _ = sel.select(source)
    for category in (Category.UNANSWERABLE, Category.INJECTION):
        wanted = sorted(c.id for c in source if c.category is category)[:2]
        assert sorted(c.id for c in live if c.category is category) == wanted


def test_the_fill_prefers_distinct_clusters(source: list[TestCase]) -> None:
    live, _ = sel.select(source)
    fill = [c for c in live if c.category is Category.FACTUAL]
    distinct = {c.cluster_id for c in fill}
    available = {c.cluster_id for c in source if c.category is Category.FACTUAL}
    assert len(distinct) >= len(available) - 1


def test_two_runs_are_byte_identical(source: list[TestCase], tmp_path: Path) -> None:
    one = sel.build_outputs(SOURCE, sel.CORPUS_MANIFEST)
    two = sel.build_outputs(SOURCE, sel.CORPUS_MANIFEST)
    assert one == two
    assert set(one) == {"smoke_live.jsonl", "smoke.jsonl", "dataset_manifest.json"}
    manifest = json.loads(one["dataset_manifest.json"])
    assert manifest["splits"] == {"smoke_live": 20, "smoke": 20}


@pytest.mark.parametrize(
    ("category", "word"),
    [
        (Category.INJECTION, "injection"),
        (Category.UNANSWERABLE, "unanswerable"),
        (Category.SYSTEM_PROMPT_EXTRACTION, "system_prompt_extraction"),
    ],
)
def test_a_missing_quota_is_named(source: list[TestCase], category: Category, word: str) -> None:
    keep = [c for c in source if c.category is not category]
    only_one = [c for c in source if c.category is category][:1]
    if category is Category.SYSTEM_PROMPT_EXTRACTION:
        only_one = []
    with pytest.raises(sel.SelectionError, match=word):
        sel.select([*keep, *only_one])


def test_a_missing_leak_probe_for_a_tenant_is_named(source: list[TestCase]) -> None:
    kept = [
        c
        for c in source
        if not (c.category is Category.LEAK_PROBE and c.tenant == "stadtwerke_sued")
    ]
    with pytest.raises(sel.SelectionError, match="stadtwerke_sued"):
        sel.select(kept)


def test_too_few_factual_cases_with_citations_are_reported(source: list[TestCase]) -> None:
    kept = [c for c in source if c.category is not Category.FACTUAL]
    with pytest.raises(sel.SelectionError, match="factual"):
        sel.select(kept)


def test_check_passes_on_the_committed_files_and_fails_on_drift(tmp_path: Path) -> None:
    assert sel.main(["--check"]) == 0
    out = tmp_path / "slice_v1"
    assert sel.main(["--out", str(out)]) == 0
    assert sel.main(["--check", "--out", str(out)]) == 0
    (out / "smoke.jsonl").write_text("drift\n", encoding="utf-8")
    assert sel.main(["--check", "--out", str(out)]) == 1


def test_a_row_with_a_split_field_is_refused(tmp_path: Path) -> None:
    row = json.loads(SOURCE.read_text(encoding="utf-8").splitlines()[0])
    row["split"] = "smoke"
    bad = tmp_path / "bad.jsonl"
    bad.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    with pytest.raises(sel.SelectionError, match="split"):
        sel.load_source(bad)


def test_fewer_than_two_english_factual_cases_are_an_error(source: list[TestCase]) -> None:
    kept = [c for c in source if not (c.category is Category.FACTUAL and c.lang.value == "en")]
    english = [c for c in source if c.category is Category.FACTUAL and c.lang.value == "en"][:1]
    with pytest.raises(sel.SelectionError, match="English"):
        sel.select([*kept, *english])


def _round() -> dict[str, object]:
    return {
        "round": 1,
        "prompt_version": "hand",
        "sampled": 40,
        "bad": 0,
        "error_rate": 0.0,
        "reviewer": "owner",
        "date": "2026-11-03",
    }


def test_the_default_review_list_is_empty_and_the_manifest_claims_no_review() -> None:
    assert json.loads(sel.REVIEW_ROUNDS.read_text(encoding="utf-8")) == []
    out = sel.build_outputs(SOURCE, sel.CORPUS_MANIFEST)
    assert json.loads(out["dataset_manifest.json"])["review"] == []


def test_review_rounds_from_the_source_file_enter_the_manifest(tmp_path: Path) -> None:
    path = tmp_path / "rounds.json"
    path.write_text(json.dumps([_round()]), encoding="utf-8")
    out = sel.build_outputs(SOURCE, sel.CORPUS_MANIFEST, review_rounds=path)
    review = json.loads(out["dataset_manifest.json"])["review"]
    assert [r["reviewer"] for r in review] == ["owner"]
    assert sel.main(["--check", "--review", str(path)]) == 1  # the committed manifest has none


@pytest.mark.parametrize(
    "text", ['{"round": 1}', '[{"round": 1}]', "not json", json.dumps([{**_round(), "x": 1}])]
)
def test_a_bad_review_file_is_refused(tmp_path: Path, text: str) -> None:
    path = tmp_path / "rounds.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(sel.SelectionError, match="review"):
        sel.build_outputs(SOURCE, sel.CORPUS_MANIFEST, review_rounds=path)


def test_an_oversized_review_file_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "rounds.json"
    path.write_text("[" + " " * 100_000 + "]", encoding="utf-8")
    with pytest.raises(sel.SelectionError, match="review"):
        sel.build_outputs(SOURCE, sel.CORPUS_MANIFEST, review_rounds=path)


def test_the_manifest_licence_text_does_not_over_claim() -> None:
    out = json.loads(sel.build_outputs(SOURCE, sel.CORPUS_MANIFEST)["dataset_manifest.json"])
    assert "UrhG" in out["license_configs"]["laws_eurlex"]
