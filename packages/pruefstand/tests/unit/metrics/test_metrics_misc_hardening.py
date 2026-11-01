"""Cost cap of the citation metrics, wider language set, refusal phrases, registry guard, nDCG gaps."""

import math
import time

import pytest

from pruefstand.core.config.gate import KNOWN_METRICS
from pruefstand.core.errors import ConfigError
from pruefstand.core.models.metric import MetricKind, MetricStatus
from pruefstand.metrics.deterministic.citation import (
    CitationF1,
    CitationGrounded,
    CitationPrecision,
    CitationRecall,
)
from pruefstand.metrics.deterministic.language import LanguageMatch
from pruefstand.metrics.deterministic.refusal import is_refusal
from pruefstand.metrics.deterministic.retrieval import NdcgAtK
from pruefstand.metrics.registry import MetricRegistry, evaluate_deterministic
from testsupport.metric_types import CaseFactory, ChunkFactory, RespFactory

CITATION_METRICS = (CitationPrecision(), CitationRecall(), CitationF1(), CitationGrounded())


def test_huge_answer_is_capped_and_fast(
    make_case: CaseFactory, make_chunk: ChunkFactory, make_resp: RespFactory
) -> None:
    filler = "Nach § 622 Abs. 2 BGB und § 623 BGB gilt: Art. 6 Abs. 1 DSGVO. " * 6_500  # ~400k chars
    chunks = [make_chunk("bgb-622", text=filler, rank=i + 1) for i in range(5)]
    resp = make_resp(filler, chunks=chunks)
    start = time.perf_counter()
    values = [m.compute(make_case(), resp) for m in CITATION_METRICS]
    assert time.perf_counter() - start < 10.0
    assert all(v.status is MetricStatus.OK for v in values)
    assert all(v.details["truncated"] is True for v in values)


def test_short_answers_are_not_reported_truncated(
    make_case: CaseFactory, make_chunk: ChunkFactory, make_resp: RespFactory
) -> None:
    resp = make_resp("Nach § 622 Abs. 2 BGB.", chunks=[make_chunk(text="§ 622 Abs. 2 BGB")])
    for metric in CITATION_METRICS:
        assert "truncated" not in metric.compute(make_case(), resp).details


def test_citation_beyond_the_cap_is_not_seen(make_case: CaseFactory, make_resp: RespFactory) -> None:
    answer = "Text. " * 5_000 + "Nach § 622 Abs. 2 BGB."
    value = CitationRecall().compute(make_case(), make_resp(answer))
    assert value.value == 0.0
    assert value.details["truncated"] is True


def test_predicted_citations_are_computed_once_per_response(
    make_case: CaseFactory, make_resp: RespFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pruefstand.metrics.deterministic import citation

    calls = []
    original = citation.extract_citations
    monkeypatch.setattr(citation, "extract_citations", lambda t: calls.append(t) or original(t))
    resp = make_resp("Nach § 622 Abs. 2 BGB gilt das, siehe auch § 623 BGB (einzigartig-9f3a).")
    for metric in CITATION_METRICS[:3]:
        metric.compute(make_case(), resp)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "answer",
    [
        "Les documents ne contiennent aucune information sur cette question juridique.",
        "Los documentos no contienen ninguna información sobre esta cuestión jurídica.",
        "Questo documento non contiene alcuna informazione su questa domanda giuridica.",
    ],
)
def test_confident_foreign_language_is_zero_not_na(
    answer: str, make_case: CaseFactory, make_resp: RespFactory
) -> None:
    for lang in ("de", "en"):
        value = LanguageMatch().compute(make_case(lang=lang), make_resp(answer))
        assert value.status is MetricStatus.OK
        assert value.value == 0.0


def test_code_with_english_comments_is_english(make_case: CaseFactory, make_resp: RespFactory) -> None:
    code = (
        "def notice_period(years):\n    # The notice period grows with the length of employment\n"
        "    # and is longer for the employer than for the employee.\n    return years * 30\n"
    )
    case = make_case(lang="en", question="What is the notice period?")
    assert LanguageMatch().compute(case, make_resp(code)).status in (
        MetricStatus.OK,
        MetricStatus.NOT_APPLICABLE,
    )


def test_repeated_abbreviation_does_not_crash(make_case: CaseFactory, make_resp: RespFactory) -> None:
    value = LanguageMatch().compute(make_case(), make_resp("BGB " * 30))
    assert value.status in (MetricStatus.OK, MetricStatus.NOT_APPLICABLE)


@pytest.mark.parametrize(
    "answer",
    [
        "Keinerlei Information dazu in den Dokumenten.",
        "Das Dokument enthält keine Information zu dieser Frage.",
        "Leider enthalten die Dokumente dazu keine Angaben.",
        "In den Dokumenten ist dazu nichts enthalten.",
        "Dazu finde ich in den Unterlagen nichts.",
        "Ich möchte hierzu keine Aussage treffen.",
        "Das Dokument enthält dazu keine Informationen.",
    ],
)
def test_more_refusal_phrases(answer: str) -> None:
    assert is_refusal(answer)


def test_ndcg_ignores_the_eleventh_of_twelve_chunks(
    make_case: CaseFactory, make_chunk: ChunkFactory, make_resp: RespFactory
) -> None:
    chunks = [make_chunk(f"f{i}", rank=i + 1) for i in range(10)]
    chunks += [make_chunk("late", rank=11), make_chunk("later", rank=12)]
    case = make_case(gold_doc_ids=["late", "later"])
    assert NdcgAtK().compute(case, make_resp(chunks=chunks)).value == 0.0


def test_ndcg_counts_a_duplicate_doc_once_without_clamp_help(
    make_case: CaseFactory, make_chunk: ChunkFactory, make_resp: RespFactory
) -> None:
    case = make_case(gold_doc_ids=["a", "b"])
    chunks = [make_chunk("a", rank=1), make_chunk("a", rank=2), make_chunk("x", rank=3)]
    expected = 1.0 / (1.0 + 1.0 / math.log2(3))
    assert NdcgAtK().compute(case, make_resp(chunks=chunks)).value == pytest.approx(expected)


def test_registry_rejects_a_deterministic_metric_without_compute() -> None:
    class NoCompute:
        name = "context_recall"
        version = "1"
        kind = MetricKind.DETERMINISTIC
        higher_is_better = True
        requires: frozenset[str] = frozenset()
        applies_to = None

    assert "context_recall" in KNOWN_METRICS
    with pytest.raises(ConfigError, match="no compute"):
        MetricRegistry([NoCompute()])


def test_evaluate_deterministic_caches_nothing_between_responses(
    make_case: CaseFactory, make_resp: RespFactory
) -> None:
    metrics = MetricRegistry.default().all()
    a = evaluate_deterministic(make_case(), make_resp("Nach § 622 Abs. 2 BGB."), metrics)
    b = evaluate_deterministic(make_case(), make_resp("Kein Bezug."), metrics)
    assert {v.metric: v.value for v in a}["citation_recall"] == 1.0
    assert {v.metric: v.value for v in b}["citation_recall"] == 0.0
