"""T7.3 S0b: ``evidence_recall`` and ``normalise_span`` on real law text (X3.2, D122)."""

import unicodedata
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from rq1.evidence_recall import METRIC, evidence_recall, normalise_span

from pruefstand.core.config.gate import KNOWN_METRICS
from pruefstand.core.ids import ChunkId, DocId
from pruefstand.core.models.metric import MetricStatus
from pruefstand.core.models.target import RetrievedChunk
from pruefstand.core.models.testcase import TestCase
from pruefstand.metrics.registry import MetricRegistry

SPAN = "Die Kündigungsfrist beträgt vier Wochen."
# § 622 Abs. 1 BGB plus the span sentence, with a line-break hyphenation as a PDF export has it.
LAW = (
    "(1) Das Arbeitsverhältnis eines Arbeiters oder eines Angestellten (Arbeitnehmers) kann "
    "mit einer Frist von vier Wochen zum Fünfzehnten oder zum Ende eines Kalendermonats "
    "gekündigt werden. Die Kündi-\n"
    "gungsfrist beträgt vier Wochen."
)
_BASE: dict[str, Any] = {
    "id": "rq1-0001",
    "base_id": "rq1-0001",
    "cluster_id": "bgb_622",
    "tenant": "shared_public",
    "lang": "de",
    "question": "Wie lang ist die Kündigungsfrist für Arbeitnehmer nach § 622 BGB?",
    "reference_answer": "Vier Wochen zum Fünfzehnten oder zum Monatsende.",
    "gold_doc_ids": ["bgb_622"],
    "evidence_span": SPAN,
    "category": "factual",
    "difficulty": "easy",
    "split": "rq1",
    "source": "generated+reviewed",
    "license_config": "laws_eurlex",
    "corpus_version": "2026-11-02.ab12cd34",
}


def _case(**changes: Any) -> TestCase:
    return TestCase.model_validate({**_BASE, **changes})


def _chunk(text: str, rank: int = 1) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=ChunkId(f"bgb_622#{rank}"),
        doc_id=DocId("bgb_622"),
        text=text,
        score=1.0 / rank,
        rank=rank,
    )


def test_line_break_hyphenation_in_the_chunk_still_contains_the_span() -> None:
    value = evidence_recall(_case(), [_chunk("§ 621 BGB ...", 1), _chunk(LAW, 2)])
    assert value.status is MetricStatus.OK
    assert value.value == 1.0
    assert value.metric == METRIC


def test_span_split_across_two_chunks_scores_zero() -> None:
    head, tail = "(1) Die Kündigungsfrist beträgt", "vier Wochen."
    value = evidence_recall(_case(), [_chunk(head, 1), _chunk(tail, 2)])
    assert value.status is MetricStatus.OK
    assert value.value == 0.0


def test_case_without_span_is_not_applicable() -> None:
    value = evidence_recall(_case(evidence_span=None), [_chunk(LAW)])
    assert value.status is MetricStatus.NOT_APPLICABLE
    assert value.value is None
    assert value.details == {"reason": "no_evidence_span"}


def test_whitespace_nbsp_and_soft_hyphen_differences_are_ignored() -> None:
    chunk = "Die Kündi­gungsfrist \t beträgt\n vier Wochen."
    assert evidence_recall(_case(), [_chunk(chunk)]).value == 1.0


def test_nfd_umlauts_equal_nfc_umlauts() -> None:
    chunk = unicodedata.normalize("NFD", LAW)
    assert chunk != LAW
    assert evidence_recall(_case(), [_chunk(chunk)]).value == 1.0
    nfd_span = _case(evidence_span=unicodedata.normalize("NFD", SPAN))
    assert evidence_recall(nfd_span, [_chunk(LAW)]).value == 1.0


def test_hyphen_before_an_upper_case_word_is_kept() -> None:
    assert normalise_span("Recht der EU-\nMitgliedstaaten") == "Recht der EU-Mitgliedstaaten"


def test_other_text_does_not_contain_the_span() -> None:
    other = "Die Kündigungsfrist beträgt einen Monat zum Ende eines Kalendermonats."
    assert evidence_recall(_case(), [_chunk(other)]).value == 0.0


def test_is_an_experiment_metric_not_registered_for_the_gate() -> None:
    assert METRIC not in KNOWN_METRICS
    assert METRIC not in MetricRegistry.default().directions()


@given(st.text(alphabet=st.characters(categories=["L", "Zs", "Cc", "Pd"]), max_size=60))
def test_normalise_span_is_idempotent(text: str) -> None:
    once = normalise_span(text)
    assert normalise_span(once) == once


@pytest.mark.parametrize("text", ["", "   ", "\n "])
def test_blank_text_normalises_to_empty(text: str) -> None:
    assert normalise_span(text) == ""
