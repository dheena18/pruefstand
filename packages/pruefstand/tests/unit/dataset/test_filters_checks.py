"""Evidence/citation check, cluster overlap of pairs and the style report (T4.3)."""

import unicodedata

from testsupport.qa_support import as_chunk, chunk, slice_chunks

from pruefstand.core.enums import Lang
from pruefstand.core.ids import ChunkId
from pruefstand.core.models.corpus import Chunk
from pruefstand.core.models.dataset import QACandidate
from pruefstand.dataset.filters_checks import (
    check_evidence,
    drop_cluster_overlap,
    style_report,
)
from pruefstand.dataset.filters_scope import absaetze_of

G1 = chunk("gii-bgb-622#1")
G0 = chunk("gii-bgb-622#0")
OTHER = chunk("gii-bgb-626#0")
ARB = chunk("gii-arbzg-3#0")
EVIDENCE = "1. zwei Jahre bestanden hat, einen Monat zum Ende eines Kalendermonats,"


def _cand(chunk_id: str = G1.chunk_id, **changes: object) -> QACandidate:
    fields: dict[str, object] = {
        "question": f"Frage zu {chunk_id} {changes.get('tag', '')}?",
        "answer": "Einen Monat.",
        "citation": "§ 622 Abs. 2 BGB",
        "chunk_id": chunk_id,
        "prompt_version": "qa_factual_de_v1",
        "evidence_span": EVIDENCE,
    }
    changes.pop("tag", None)
    return QACandidate.model_validate({**fields, **changes})


def test_a_valid_citation_and_evidence_pass() -> None:
    assert check_evidence(_cand(), [G1]).kept


def test_a_citation_of_another_paragraph_is_a_mismatch() -> None:
    assert check_evidence(_cand(citation="§ 1 KSchG"), [G1]).reasons == ("citation_mismatch",)


def test_evidence_of_another_absatz_is_rejected() -> None:
    other_absatz = "Während einer vereinbarten Probezeit, längstens für die Dauer von sechs Monaten"
    got = check_evidence(_cand(evidence_span=other_absatz), [G0, G1])
    assert got.reasons == ("evidence_off_paragraph",)


def test_the_whole_chunk_is_not_accepted_when_the_citation_names_another_chunk() -> None:
    # the citation names § 626 only; the evidence is a real span, but of the uncited § 622 chunk
    pair = _cand(citation="§ 626 Abs. 1 BGB", extra_chunk_ids=(OTHER.chunk_id,))
    got = check_evidence(pair, [G1, OTHER])
    assert got.reasons == ("evidence_off_paragraph",)


def test_a_citation_without_absatz_accepts_the_whole_chunk() -> None:
    assert check_evidence(_cand(citation="§ 622 BGB"), [G1]).kept


def _pair(first: str, second: str, tag: str = "") -> QACandidate:
    return _cand(
        first,
        prompt_version="qa_multi_hop_de_v1",
        extra_chunk_ids=(second,),
        evidence_span=None,
        tag=tag,
    )


CHUNKS = {c.chunk_id: c for c in (G1, G0, OTHER, ARB)}


def test_a_pair_on_the_cluster_of_a_factual_case_is_dropped() -> None:
    single = _cand(OTHER.chunk_id, citation=None, evidence_span=None)
    pair = _pair(G1.chunk_id, OTHER.chunk_id)
    kept, dropped = drop_cluster_overlap([pair, single], CHUNKS)
    assert kept == [single]
    assert dropped == [pair]


def test_pairs_with_distinct_documents_are_kept() -> None:
    single = _cand(ARB.chunk_id, citation=None, evidence_span=None)
    pair = _pair(G1.chunk_id, OTHER.chunk_id)
    assert drop_cluster_overlap([single, pair], CHUNKS) == ([single, pair], [])


def test_a_pair_whose_cluster_is_another_pairs_second_document_is_dropped_once() -> None:
    a, b = _pair(G1.chunk_id, OTHER.chunk_id), _pair(OTHER.chunk_id, G1.chunk_id)
    kept, dropped = drop_cluster_overlap([a, b], CHUNKS)
    assert len(kept) == 1
    assert len(dropped) == 1
    assert drop_cluster_overlap([b, a], CHUNKS)[0] == kept  # same pair survives in any order


def test_cross_lingual_pairs_of_one_norm_do_not_conflict_with_themselves() -> None:
    de = as_chunk(G1, chunk_id="n-de#0", doc_id="n-de", parallel_id="x:1")
    en = as_chunk(G1, chunk_id="n-en#0", doc_id="n-en", parallel_id="x:1", lang=Lang.EN)
    pair = _cand(
        de.chunk_id,
        prompt_version="qa_cross_lingual_de_v1",
        extra_chunk_ids=(en.chunk_id,),
        evidence_span=None,
    )
    kept, dropped = drop_cluster_overlap([pair], {de.chunk_id: de, en.chunk_id: en})
    assert (kept, dropped) == ([pair], [])


def test_the_style_share_is_reported_from_the_minimum_count() -> None:
    cands = [_cand(style="laie", tag=str(i)) for i in range(5)] + [
        _cand(style="fachlich", tag="f")
    ] * 5
    report = style_report(cands, 0.6, 10)
    assert (report.laie, report.fachlich, report.share, report.ok) == (5, 5, 0.5, False)
    assert style_report(cands[:4], 0.6, 10).ok is None
    assert style_report([_cand()], 0.6, 1).unknown == 1


ART5_0 = chunk("eurlex-32016r0679-art-5-de#0")
ART5_1 = chunk("eurlex-32016r0679-art-5-de#1")
ART6_0 = chunk("eurlex-32016r0679-art-6-de#0")
ART6_1 = chunk("eurlex-32016r0679-art-6-de#1")
HEADING = "Grundsätze für die Verarbeitung personenbezogener Daten"
ART5_SENTENCE = "Personenbezogene Daten müssen"


def _dsgvo(citation: str, evidence: str | None, chunk_id: str = ART5_0.chunk_id) -> QACandidate:
    return QACandidate(
        question="Was verlangt die DSGVO?", answer="Rechtmäßigkeit.", citation=citation,
        chunk_id=ChunkId(chunk_id), prompt_version="qa_factual_de_v1", evidence_span=evidence,
    )  # fmt: skip


def test_an_absatz_the_chunk_does_not_have_does_not_accept_the_heading() -> None:
    # regression (review of #76): Abs. 9 does not exist; the text before "(1)" is the heading
    got = check_evidence(_dsgvo("Art. 5 Abs. 9 DSGVO", HEADING), [ART5_0])
    assert got.reasons == ("evidence_not_in_cited_absatz",)
    heading6 = ART6_0.text.split("\n")[0]
    assert check_evidence(
        _dsgvo("Art. 6 Abs. 9 DSGVO", heading6, ART6_0.chunk_id), [ART6_0]
    ).reasons == ("evidence_not_in_cited_absatz",)


def test_the_heading_is_no_evidence_for_absatz_one_either() -> None:
    got = check_evidence(_dsgvo("Art. 5 Abs. 1 DSGVO", HEADING), [ART5_0])
    assert got.reasons == ("evidence_not_in_cited_absatz",)
    assert check_evidence(_dsgvo("Art. 5 Abs. 1 DSGVO", ART5_SENTENCE), [ART5_0]).kept


def test_an_absatz_missing_from_every_chunk_of_the_norm_is_rejected() -> None:
    evidence = "Der Verantwortliche ist für die Einhaltung des Absatzes 1 verantwortlich"
    got = check_evidence(_dsgvo("Art. 5 Abs. 9 DSGVO", evidence), [ART5_0, ART5_1])
    assert got.reasons == ("evidence_not_in_cited_absatz",)


def test_ranges_of_absaetze_are_expanded() -> None:
    assert absaetze_of("Art. 5 Abs. 1 bis 3 DSGVO") == ["1", "2", "3"]
    assert absaetze_of("Art. 5 Abs. 1-2 DSGVO") == ["1", "2"]
    assert absaetze_of("§ 622 Abs. 2 und 3 BGB") == ["2", "3"]
    evidence = "Der Verantwortliche ist für die Einhaltung des Absatzes 1 verantwortlich"
    for citation in ("Art. 5 Abs. 1 bis 2 DSGVO", "Art. 5 Abs. 1-2 DSGVO"):
        assert check_evidence(_dsgvo(citation, evidence), [ART5_0, ART5_1]).kept
    assert not check_evidence(_dsgvo("Art. 5 Abs. 1 DSGVO", evidence), [ART5_0, ART5_1]).kept


def test_short_evidence_is_rejected_and_nfd_evidence_is_compared_as_nfc() -> None:
    assert check_evidence(_dsgvo("Art. 5 Abs. 1 DSGVO", "Daten müssen"), [ART5_0]).reasons == (
        "evidence_too_short",
    )
    nfd = unicodedata.normalize("NFD", "Personenbezogene Daten müssen")
    assert nfd != unicodedata.normalize("NFC", nfd)
    assert check_evidence(_dsgvo("Art. 5 Abs. 1 DSGVO", nfd), [ART5_0]).kept


def test_a_missing_or_unparsable_citation_is_a_reason() -> None:
    assert check_evidence(_dsgvo("irgendwo", ART5_SENTENCE), [ART5_0]).reasons == (
        "citation_unparsed",
    )
    got = check_evidence(_cand(citation=None, evidence_span=None), [G1])
    assert got.reasons == ("citation_missing", "evidence_missing")


ALL = {c.chunk_id: c for c in slice_chunks().values()}
EN5_0 = ALL[ChunkId("eurlex-32016r0679-art-5-en#0")]
EN5_1 = ALL[ChunkId("eurlex-32016r0679-art-5-en#1")]
EN6_2 = ALL[ChunkId("eurlex-32016r0679-art-6-en#2")]
B620 = ALL[ChunkId("gii-bgb-620#0")]
B622_2 = ALL[ChunkId("gii-bgb-622#2")]


def test_english_paragraph_markers_are_known() -> None:
    # regression (round 2): "2. " is a marker, so a later English chunk is no free continuation
    pair = _dsgvo("Art. 5 Abs. 9 DSGVO", "The controller shall be responsible")
    pair = pair.model_copy(update={"extra_chunk_ids": (EN5_1.chunk_id,)})
    assert not check_evidence(pair, [ART5_0, EN5_1], ALL).kept
    ok = _dsgvo("Art. 5 Abs. 2 DSGVO", "The controller shall be responsible", EN5_1.chunk_id)
    assert check_evidence(ok, [EN5_1], ALL).kept
    wrong = _dsgvo(
        "Art. 6 Abs. 1 DSGVO", "The basis for the processing referred to", EN6_2.chunk_id
    )
    assert not check_evidence(wrong, [EN6_2], ALL).kept
    right = _dsgvo(
        "Art. 6 Abs. 3 DSGVO", "The basis for the processing referred to", EN6_2.chunk_id
    )
    assert check_evidence(right, [EN6_2], ALL).kept


def test_the_english_heading_is_no_evidence() -> None:
    heading = "Principles relating to processing of personal data"
    for citation in ("Art. 5 Abs. 1 DSGVO", "Art. 5 DSGVO"):
        assert not check_evidence(_dsgvo(citation, heading, EN5_0.chunk_id), [EN5_0], ALL).kept
    assert check_evidence(
        _dsgvo("Art. 5 Abs. 1 DSGVO", "Personal data shall be", EN5_0.chunk_id), [EN5_0], ALL
    ).kept


def test_a_citation_without_absatz_does_not_accept_the_heading_of_a_first_chunk() -> None:
    got = check_evidence(_dsgvo("Art. 5 DSGVO", HEADING), [ART5_0], ALL)
    assert got.reasons == ("evidence_not_in_cited_absatz",)
    assert check_evidence(_dsgvo("Art. 5 DSGVO", ART5_SENTENCE), [ART5_0], ALL).kept


def _continuation(text: str) -> tuple[Chunk, dict[ChunkId, Chunk]]:
    """A later chunk without markers that continues Absatz 2 of art-6-de#1 (real text)."""
    later = as_chunk(ART6_1, chunk_id=ChunkId("eurlex-32016r0679-art-6-de#2"), text=text)
    return later, {**ALL, later.chunk_id: later}


def test_a_continuation_chunk_accepts_only_the_absatz_it_continues() -> None:
    tail = ART6_1.text[4:200]
    later, chunks = _continuation(tail)
    evidence = " ".join(tail.split()[:8])
    assert check_evidence(
        _dsgvo("Art. 6 Abs. 2 DSGVO", evidence, later.chunk_id), [later], chunks
    ).kept
    for bad in ("Art. 6 Abs. 9 DSGVO", "Art. 6 Abs. 1 DSGVO", "Art. 6 Abs. 0 DSGVO"):
        assert not check_evidence(_dsgvo(bad, evidence, later.chunk_id), [later], chunks).kept
    assert not check_evidence(_dsgvo("Art. 6 Abs. 2 DSGVO", evidence, later.chunk_id), [later]).kept


def test_lead_text_before_a_marker_belongs_to_the_previous_absatz() -> None:
    tail = ART6_1.text[4:200]
    later, chunks = _continuation(tail + "\n" + chunk("eurlex-32016r0679-art-6-de#2").text)
    evidence = " ".join(tail.split()[:8])
    assert check_evidence(
        _dsgvo("Art. 6 Abs. 2 DSGVO", evidence, later.chunk_id), [later], chunks
    ).kept
    assert not check_evidence(
        _dsgvo("Art. 6 Abs. 9 DSGVO", evidence, later.chunk_id), [later], chunks
    ).kept
    first = as_chunk(later, chunk_id=ChunkId("eurlex-32016r0679-art-6-de#0"))
    assert not check_evidence(
        _dsgvo("Art. 6 Abs. 2 DSGVO", evidence, first.chunk_id), [first], chunks
    ).kept


def test_evidence_may_span_two_cited_absaetze_and_must_not_leave_them() -> None:
    span = "Ablauf der Zeit, für die es eingegangen ist.\n(2) Ist die Dauer des Dienstverhältnisses"

    def cand(citation: str) -> QACandidate:
        return _dsgvo(citation, span, B620.chunk_id)

    assert check_evidence(cand("§ 620 Abs. 1 und 2 BGB"), [B620], ALL).kept
    assert check_evidence(cand("§ 620 Abs. 1 bis 2 BGB"), [B620], ALL).kept
    assert not check_evidence(cand("§ 620 Abs. 1 BGB"), [B620], ALL).kept
    assert not check_evidence(cand("§ 620 Abs. 0 BGB"), [B620], ALL).kept


def test_a_range_applies_to_its_own_norm_in_a_two_norm_citation() -> None:
    evidence = "Der Verantwortliche ist für die Einhaltung des Absatzes 1 verantwortlich"
    cand = _dsgvo("Art. 5 Abs. 1 bis 2 DSGVO; § 623 BGB", evidence)
    assert check_evidence(cand, [ART5_0, ART5_1], ALL).kept
    cand = _dsgvo("§ 623 BGB; Art. 5 Abs. 1 bis 2 DSGVO", evidence)
    assert check_evidence(cand, [ART5_0, ART5_1], ALL).kept


def test_evidence_must_match_whole_words_and_markers_do_not_count() -> None:

    def cand(evidence: str) -> QACandidate:
        return _dsgvo("§ 622 Abs. 3 BGB", evidence, B622_2.chunk_id)

    assert check_evidence(cand("Während einer vereinbarten Probezeit"), [B622_2], ALL).kept
    assert not check_evidence(cand("ährend einer vereinbarten Pro"), [B622_2], ALL).kept
    assert check_evidence(cand("(3) Während einer"), [B622_2], ALL).reasons == (
        "evidence_too_short",
    )
