"""Structural checks of `datasets/fixtures/slice_v1` against the real slice corpus (T1.11 S5)."""

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
from fixtures import select_smoke_live as sel
from typer.testing import CliRunner

from pruefstand.cli import app
from pruefstand.core.enums import Category, Split
from pruefstand.core.models.dataset import DatasetManifest
from pruefstand.core.models.testcase import TestCase
from pruefstand.metrics.deterministic.normalise import compile_forbidden

ROOT = Path(__file__).resolve().parents[4]
DATASET = ROOT / "datasets" / "fixtures" / "slice_v1"
CORPUS = ROOT / "corpus" / "slice_v1"
PROMPT = ROOT / "apps" / "rag-demo" / "src" / "rag_demo" / "prompts" / "answer_de_v1.txt"
ANSWERABLE = {Category.FACTUAL, Category.MULTI_HOP, Category.COMPARISON, Category.CROSS_LINGUAL}
PRIVATE = "versicherung_nord"
NGRAM = 8


def _chunks() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(CORPUS.glob("*.chunks.jsonl")):
        rows += [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    return rows


@pytest.fixture(scope="module")
def chunks() -> list[dict[str, Any]]:
    return _chunks()


@pytest.fixture(scope="module")
def cases() -> list[TestCase]:
    out: list[TestCase] = []
    for split in (Split.SMOKE_LIVE, Split.SMOKE):
        lines = (DATASET / f"{split.value}.jsonl").read_text(encoding="utf-8").splitlines()
        out += [TestCase.model_validate_json(line) for line in lines]
    return out


def _words(text: str) -> list[str]:
    return re.findall(r"\w+", text.casefold())


def test_validate_dataset_accepts_both_splits() -> None:
    result = CliRunner().invoke(app, ["validate", "dataset", str(DATASET)])
    assert result.exit_code == 0, result.output
    assert "40 valid cases" in result.output


def test_the_split_files_equal_a_fresh_selection() -> None:
    fresh = sel.build_outputs(sel.SOURCE, sel.CORPUS_MANIFEST)
    for name, text in fresh.items():
        assert (DATASET / name).read_text(encoding="utf-8") == text, name


def test_category_counts_over_both_files(cases: list[TestCase]) -> None:
    counts = Counter(c.category.value for c in cases)
    assert counts == {
        "factual": 14,
        "multi_hop": 4,
        "comparison": 2,
        "unanswerable": 5,
        "cross_lingual": 4,
        "injection": 4,
        "leak_probe": 4,
        "system_prompt_extraction": 2,
        "filter_bypass": 1,
    }
    factual = [c for c in cases if c.category is Category.FACTUAL]
    assert Counter(c.lang.value for c in factual) == {"de": 10, "en": 4}


def test_manifest_matches_the_files_and_the_corpus() -> None:
    manifest = DatasetManifest.model_validate_json(
        (DATASET / "dataset_manifest.json").read_text(encoding="utf-8")
    )
    corpus = json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))
    assert manifest.corpus_version == corpus["corpus_version"]
    assert manifest.splits == {Split.SMOKE_LIVE: 20, Split.SMOKE: 20}
    assert set(manifest.license_configs) == {"laws_eurlex", "own"}


def test_every_case_is_hand_written_with_a_licence_and_the_corpus_version(
    cases: list[TestCase],
) -> None:
    corpus = json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))
    assert len({c.id for c in cases}) == 40
    for case in cases:
        assert case.source == "hand"
        assert case.corpus_version == corpus["corpus_version"]
        wanted = "laws_eurlex" if case.category in ANSWERABLE else "own"
        assert case.license_config == wanted, case.id


def test_every_gold_doc_exists_and_is_visible_to_the_asking_tenant(
    cases: list[TestCase], chunks: list[dict[str, Any]]
) -> None:
    owner = {c["doc_id"]: c["tenant"] for c in chunks}
    for case in cases:
        for doc in case.gold_doc_ids:
            assert doc in owner, (case.id, doc)
            assert owner[doc] in {case.tenant, "shared_public"}, (case.id, doc)
        if case.category in ANSWERABLE:
            assert case.gold_doc_ids, case.id
            assert case.gold_citations, case.id
            assert case.reference_answer, case.id


def test_gold_citations_name_the_gold_norms_and_evidence_is_verbatim(
    cases: list[TestCase], chunks: list[dict[str, Any]]
) -> None:
    keys: dict[str, set[str]] = {}
    text: dict[str, str] = {}
    for c in chunks:
        keys.setdefault(c["doc_id"], set()).add(c["citation_key"] or "")
        text[c["doc_id"]] = text.get(c["doc_id"], "") + " " + " ".join(c["text"].split())
    detail = re.compile(r"\s+(?:Abs\.|Satz|S\.|Nr\.)\s*\d+")
    for case in cases:
        if case.category not in ANSWERABLE:
            continue
        wanted = set().union(*(keys[d] for d in case.gold_doc_ids))
        for citation in case.gold_citations:
            assert detail.sub("", citation) in wanted, (case.id, citation)
        if case.evidence_span:
            haystack = " ".join(text[d] for d in case.gold_doc_ids)
            assert " ".join(case.evidence_span.split()) in haystack, case.id


def test_cross_lingual_questions_cross_the_language_of_the_gold_text(
    cases: list[TestCase], chunks: list[dict[str, Any]]
) -> None:
    lang = {c["doc_id"]: c["lang"] for c in chunks}
    for case in cases:
        gold = {lang[d] for d in case.gold_doc_ids}
        if case.category is Category.CROSS_LINGUAL:
            assert gold == {"en" if case.lang.value == "de" else "de"}, case.id
        elif case.category in ANSWERABLE:
            assert gold == {case.lang.value}, case.id
    pairs = Counter(c.lang.value for c in cases if c.category is Category.CROSS_LINGUAL)
    assert pairs == {"en": 2, "de": 2}


def test_leak_probe_strings_occur_only_in_the_private_tenant(
    cases: list[TestCase], chunks: list[dict[str, Any]]
) -> None:
    probes = [c for c in cases if c.category is Category.LEAK_PROBE]
    assert {c.tenant for c in probes} == {"kanzlei_mueller", "stadtwerke_sued"}
    for case in probes:
        assert len(case.forbidden_strings) >= 2
        for forbidden in case.forbidden_strings:
            matcher = compile_forbidden(forbidden)
            hit = {c["tenant"] for c in chunks if matcher.matches(c["text"])}
            assert hit == {PRIVATE}, (case.id, forbidden, hit)


def test_filter_bypass_string_occurs_only_in_a_foreign_tenant(
    cases: list[TestCase], chunks: list[dict[str, Any]]
) -> None:
    (case,) = [c for c in cases if c.category is Category.FILTER_BYPASS]
    for forbidden in case.forbidden_strings:
        matcher = compile_forbidden(forbidden)
        hit = {c["tenant"] for c in chunks if matcher.matches(c["text"])}
        assert hit, forbidden
        assert hit.isdisjoint({case.tenant, "shared_public"}), forbidden


def test_system_prompt_strings_are_in_the_prompt_and_in_no_chunk(
    cases: list[TestCase], chunks: list[dict[str, Any]]
) -> None:
    prompt = PROMPT.read_text(encoding="utf-8")
    probes = [c for c in cases if c.category is Category.SYSTEM_PROMPT_EXTRACTION]
    assert len(probes) == 2
    for case in probes:
        for forbidden in case.forbidden_strings:
            matcher = compile_forbidden(forbidden)
            assert matcher.matches(prompt), (case.id, forbidden)
            assert not any(matcher.matches(c["text"]) for c in chunks), (case.id, forbidden)


def test_injection_markers_come_from_the_planted_documents_only(
    cases: list[TestCase], chunks: list[dict[str, Any]]
) -> None:
    injections = [c for c in cases if c.category is Category.INJECTION]
    assert len({c.injection_marker for c in injections}) == 4
    for case in injections:
        assert case.injection_marker
        hit = [c for c in chunks if case.injection_marker in c["text"]]
        assert hit, case.id
        assert all(c["is_attack"] for c in hit), case.id
        assert hit[0]["tenant"] in {case.tenant, "shared_public"}, case.id


def test_unanswerable_cases_have_no_gold_and_expect_a_refusal(cases: list[TestCase]) -> None:
    for case in cases:
        if case.category is Category.UNANSWERABLE:
            assert case.expect_refusal, case.id
            assert not case.gold_doc_ids, case.id


def test_no_question_shares_an_8_gram_with_a_chunk(
    cases: list[TestCase], chunks: list[dict[str, Any]]
) -> None:
    grams: set[tuple[str, ...]] = set()
    for chunk in chunks:
        words = _words(chunk["text"])
        grams |= {tuple(words[i : i + NGRAM]) for i in range(len(words) - NGRAM + 1)}
    for case in cases:
        words = _words(case.question)
        shared = [
            w for i in range(len(words) - NGRAM + 1) if (w := tuple(words[i : i + NGRAM])) in grams
        ]
        assert not shared, (case.id, shared[:1])


def test_clusters_cover_the_gates_minimum(cases: list[TestCase]) -> None:
    assert len({c.cluster_id for c in cases}) >= 30
    answerable = {c.cluster_id for c in cases if c.category in ANSWERABLE}
    assert len(answerable) >= 16
