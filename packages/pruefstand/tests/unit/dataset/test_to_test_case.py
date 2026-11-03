"""``to_test_case`` (T4.2): candidate -> ``TestCase`` with cluster, licence and evidence span."""

import pytest
from testsupport.qa_support import as_chunk, chunk

from pruefstand.core.enums import Category, Lang, Split
from pruefstand.core.errors import DatasetError
from pruefstand.core.models.dataset import QACandidate
from pruefstand.dataset.to_case import license_config_of, to_test_case

CORPUS = "slice-2026-10-31.51fd4b94"
EVIDENCE = "1. zwei Jahre bestanden hat, einen Monat zum Ende eines Kalendermonats,"


def _cand(**changes: object) -> QACandidate:
    fields: dict[str, object] = {
        "question": "Wie lange muss mein Arbeitgeber mir vorher kündigen?",
        "answer": "Einen Monat zum Ende eines Kalendermonats.",
        "citation": "§ 622 Abs. 2 Nr. 1 BGB",
        "chunk_id": "gii-bgb-622#1",
        "prompt_version": "qa_factual_de_v1",
        "evidence_span": EVIDENCE,
        "style": "laie",
    }
    return QACandidate.model_validate({**fields, **changes})


def test_factual_case_fields() -> None:
    case = to_test_case(_cand(), chunk("gii-bgb-622#1"), Category.FACTUAL, corpus_version=CORPUS)
    assert case.base_id == case.id
    assert case.cluster_id == "gii-bgb-622"
    assert case.source == "generated"
    assert case.generation_prompt_version == "qa_factual_de_v1"
    assert case.gold_citations == ("§ 622 Abs. 2 BGB",)
    assert case.gold_doc_ids == ("gii-bgb-622",)
    assert case.evidence_span == EVIDENCE
    assert case.reference_answer == "Einen Monat zum Ende eines Kalendermonats."
    assert case.tenant == "shared_public"
    assert case.lang is Lang.DE
    assert case.license_config == "laws_eurlex"
    assert case.perturbation is None
    assert case.corpus_version == CORPUS


def test_the_id_is_stable_and_differs_per_question() -> None:
    a = to_test_case(_cand(), chunk("gii-bgb-622#1"), Category.FACTUAL, corpus_version=CORPUS)
    b = to_test_case(_cand(), chunk("gii-bgb-622#1"), Category.FACTUAL, corpus_version=CORPUS)
    c = to_test_case(
        _cand(question="Anders?"), chunk("gii-bgb-622#1"), Category.FACTUAL, corpus_version=CORPUS
    )
    assert a.id == b.id != c.id


def test_split_and_difficulty_can_be_given() -> None:
    case = to_test_case(
        _cand(), chunk("gii-bgb-622#1"), Category.FACTUAL, corpus_version=CORPUS, split=Split.CORE
    )
    assert case.split is Split.CORE


def test_a_missing_citation_falls_back_to_the_chunks_citation_key() -> None:
    case = to_test_case(
        _cand(citation=None), chunk("gii-bgb-622#1"), Category.FACTUAL, corpus_version=CORPUS
    )
    assert case.gold_citations == ("§ 622 BGB",)


def test_multi_hop_case_has_both_documents_and_the_first_cluster() -> None:
    cand = _cand(
        extra_chunk_ids=("gii-kschg-1#1",),
        citation="§ 622 Abs. 2 BGB; § 1 Abs. 2 KSchG",
        prompt_version="qa_multi_hop_de_v1",
    )
    case = to_test_case(
        cand,
        chunk("gii-bgb-622#1"),
        Category.MULTI_HOP,
        corpus_version=CORPUS,
        extra_chunk=chunk("gii-kschg-1#1"),
    )
    assert case.gold_doc_ids == ("gii-bgb-622", "gii-kschg-1")
    assert case.gold_citations == ("§ 622 Abs. 2 BGB", "§ 1 Abs. 2 KSchG")
    assert case.cluster_id == "gii-bgb-622"


def test_cross_lingual_case_clusters_on_the_german_document() -> None:
    de, en = chunk("eurlex-32016r0679-art-6-de#0"), chunk("eurlex-32016r0679-art-6-en#0")
    cand = QACandidate(
        question="Under which conditions is processing lawful?",
        answer="If one of the grounds applies.",
        citation="Art. 6 Abs. 1 DSGVO",
        chunk_id=de.chunk_id,
        extra_chunk_ids=(en.chunk_id,),
        prompt_version="qa_cross_lingual_de_v1",
        lang=Lang.EN,
    )
    case = to_test_case(cand, de, Category.CROSS_LINGUAL, corpus_version=CORPUS, extra_chunk=en)
    assert case.cluster_id == "eurlex-32016r0679-art-6-de"
    assert case.lang is Lang.EN
    reverse = cand.model_copy(
        update={"chunk_id": en.chunk_id, "extra_chunk_ids": (de.chunk_id,), "lang": Lang.DE}
    )
    flipped = to_test_case(
        reverse, en, Category.CROSS_LINGUAL, corpus_version=CORPUS, extra_chunk=de
    )
    assert flipped.cluster_id == "eurlex-32016r0679-art-6-de"


def test_law_and_decision_pair_is_oldp_derived() -> None:
    law = chunk("gii-bgb-622#1")
    decision = as_chunk(law, source="oldp:decisions", doc_id="oldp-5", chunk_id="oldp-5#0")
    assert license_config_of([law]) == "laws_eurlex"
    assert license_config_of([law, decision]) == "oldp_derived"
    assert license_config_of([decision]) == "oldp_derived"


def test_share_alike_configs_never_mix() -> None:
    law = chunk("gii-bgb-622#1")
    quad = as_chunk(law, source="germanquad:train", doc_id="gq-1", chunk_id="gq-1#0")
    oldp = as_chunk(law, source="oldp:decisions", doc_id="oldp-5", chunk_id="oldp-5#0")
    assert license_config_of([quad]) == "germanquad_derived"
    assert license_config_of([quad, oldp]) is None


def test_a_chunk_of_an_unknown_source_has_no_licence_config() -> None:
    odd = as_chunk(chunk("gii-bgb-622#1"), source="wiki:foo")
    assert license_config_of([odd]) is None
    with pytest.raises(DatasetError, match="licen"):
        to_test_case(_cand(), odd, Category.FACTUAL, corpus_version=CORPUS)
