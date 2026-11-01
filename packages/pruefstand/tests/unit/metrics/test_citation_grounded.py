"""citation_grounded (T1.5b S2b, R9 X3.2)."""

from pruefstand.core.models.metric import MetricStatus
from pruefstand.metrics.deterministic.citation import CitationGrounded

from testsupport.metric_types import CaseFactory, ChunkFactory, RespFactory


def test_grounded_by_chunk_text(make_case: CaseFactory, make_chunk: ChunkFactory, make_resp: RespFactory) -> None:
    chunk = make_chunk(text="Die Kündigungsfrist ergibt sich aus § 622 Abs. 2 BGB und beträgt einen Monat.")
    resp = make_resp("Gemäß § 622 Abs. 2 BGB gilt ein Monat.", chunks=[chunk])
    value = CitationGrounded().compute(make_case(), resp)
    assert value.status is MetricStatus.OK
    assert value.value == 1.0


def test_hallucinated_norm_halves_the_share(
    make_case: CaseFactory, make_chunk: ChunkFactory, make_resp: RespFactory
) -> None:
    chunk = make_chunk(text="§ 622 BGB regelt die Kündigungsfristen.")
    resp = make_resp("Siehe § 622 BGB und § 999 BGB.", chunks=[chunk])
    assert CitationGrounded().compute(make_case(), resp).value == 0.5


def test_citation_in_resp_citations_is_a_prediction(
    make_case: CaseFactory, make_chunk: ChunkFactory, make_resp: RespFactory
) -> None:
    chunk = make_chunk(text="Art. 6 Abs. 1 DSGVO nennt die Rechtsgrundlagen.")
    resp = make_resp("Ja.", citations=["Art. 6 Abs. 1 DSGVO", "Art. 99 DSGVO"], chunks=[chunk])
    assert CitationGrounded().compute(make_case(), resp).value == 0.5


def test_absatz_level_mismatch_is_not_grounded(
    make_case: CaseFactory, make_chunk: ChunkFactory, make_resp: RespFactory
) -> None:
    chunk = make_chunk(text="Nach § 622 Abs. 2 BGB gilt das.")
    resp = make_resp("Nach § 622 Abs. 3 BGB gilt das.", chunks=[chunk])
    assert CitationGrounded().compute(make_case(), resp).value == 0.0


def test_not_applicable_without_citation(
    make_case: CaseFactory, make_chunk: ChunkFactory, make_resp: RespFactory
) -> None:
    resp = make_resp("Die Frist beträgt einen Monat.", chunks=[make_chunk(text="§ 622 BGB")])
    assert CitationGrounded().compute(make_case(), resp).status is MetricStatus.NOT_APPLICABLE


def test_not_applicable_without_chunks(make_case: CaseFactory, make_resp: RespFactory) -> None:
    value = CitationGrounded().compute(make_case(), make_resp("Nach § 622 BGB.", chunks=None))
    assert value.status is MetricStatus.NOT_APPLICABLE
    assert value.value is None


def test_empty_chunk_list_means_nothing_is_grounded(make_case: CaseFactory, make_resp: RespFactory) -> None:
    assert CitationGrounded().compute(make_case(), make_resp("Nach § 622 BGB.", chunks=[])).value == 0.0


def test_attributes() -> None:
    metric = CitationGrounded()
    assert metric.name == "citation_grounded"
    assert metric.higher_is_better is True
    assert metric.requires == frozenset({"chunks"})
