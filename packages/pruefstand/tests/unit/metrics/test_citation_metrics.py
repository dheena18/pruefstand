"""citation_precision / citation_recall / citation_f1 (T1.5b S2)."""

import pytest
from testsupport.metric_types import CaseFactory, RespFactory

from pruefstand.core.models.metric import MetricStatus
from pruefstand.core.models.target import TargetResponse
from pruefstand.core.models.testcase import TestCase
from pruefstand.metrics.deterministic.citation import CitationF1, CitationPrecision, CitationRecall


def prf(case: TestCase, resp: TargetResponse) -> tuple[float | None, ...]:
    return (
        CitationPrecision().compute(case, resp).value,
        CitationRecall().compute(case, resp).value,
        CitationF1().compute(case, resp).value,
    )


def test_exact_match_in_answer_text(make_case: CaseFactory, make_resp: RespFactory) -> None:
    case = make_case(gold_citations=["§ 622 BGB"])
    resp = make_resp("Die Frist ergibt sich gemäß § 622 Abs. 2 BGB aus dem Gesetz.")
    assert prf(case, resp) == (1.0, 1.0, 1.0)


def test_extra_citation_halves_precision(make_case: CaseFactory, make_resp: RespFactory) -> None:
    case = make_case(gold_citations=["§ 622 BGB"])
    resp = make_resp("Es gelten § 622 BGB und § 623 BGB.")
    p, r, f1 = prf(case, resp)
    assert (p, r) == (0.5, 1.0)
    assert f1 == pytest.approx(0.667, abs=1e-3)


def test_wrong_absatz_is_zero(make_case: CaseFactory, make_resp: RespFactory) -> None:
    case = make_case(gold_citations=["§ 622 Abs. 2 BGB"])
    assert prf(case, make_resp("Siehe § 622 Abs. 3 BGB.")) == (0.0, 0.0, 0.0)


def test_no_citation_is_zero_not_na(make_case: CaseFactory, make_resp: RespFactory) -> None:
    case = make_case(gold_citations=["§ 622 BGB"])
    resp = make_resp("Die Kündigungsfrist beträgt einen Monat.")
    assert prf(case, resp) == (0.0, 0.0, 0.0)
    assert CitationRecall().compute(case, resp).status is MetricStatus.OK


def test_gold_empty_is_not_applicable(make_case: CaseFactory, make_resp: RespFactory) -> None:
    case = make_case(gold_citations=[])
    for metric in (CitationPrecision(), CitationRecall(), CitationF1()):
        value = metric.compute(case, make_resp("§ 622 BGB"))
        assert value.status is MetricStatus.NOT_APPLICABLE
        assert value.value is None


def test_half_credit_for_missing_absatz(make_case: CaseFactory, make_resp: RespFactory) -> None:
    case = make_case(gold_citations=["§ 622 Abs. 2 BGB"])
    p, r, f1 = prf(case, make_resp("Maßgeblich ist § 622 BGB."))
    assert (p, r) == (0.5, 0.5)
    assert f1 == pytest.approx(0.5)


def test_resp_citations_and_answer_are_unioned_and_deduplicated(
    make_case: CaseFactory, make_resp: RespFactory
) -> None:
    case = make_case(gold_citations=["§ 622 Abs. 2 BGB"])
    resp = make_resp(
        "Nach § 622 Absatz 2 BGB gilt das.", citations=["§ 622 Abs. 2 BGB", "§622 Abs. 2 BGB"]
    )
    assert prf(case, resp) == (1.0, 1.0, 1.0)  # three spellings, one prediction


def test_citation_only_in_resp_citations_counts(
    make_case: CaseFactory, make_resp: RespFactory
) -> None:
    case = make_case(gold_citations=["Art. 6 Abs. 1 DSGVO"])
    resp = make_resp("Die Verarbeitung ist erlaubt.", citations=["Art. 6 Abs. 1 lit. f GDPR"])
    assert prf(case, resp) == (1.0, 1.0, 1.0)


def test_recall_is_mean_over_gold(make_case: CaseFactory, make_resp: RespFactory) -> None:
    case = make_case(gold_citations=["§ 622 BGB", "§ 1 KSchG"])
    p, r, _ = prf(case, make_resp("Es gilt § 622 BGB."))
    assert (p, r) == (1.0, 0.5)


def test_unparseable_gold_is_an_error_status(
    make_case: CaseFactory, make_resp: RespFactory
) -> None:
    case = make_case(gold_citations=["Paragraph irgendwas"])
    value = CitationRecall().compute(case, make_resp("§ 622 BGB"))
    assert value.status is MetricStatus.ERROR
    assert value.value is None
    assert value.details["error"] == "unparseable_gold_citation"


def test_direction_names_and_versions() -> None:
    names = {m.name for m in (CitationPrecision(), CitationRecall(), CitationF1())}
    assert names == {"citation_precision", "citation_recall", "citation_f1"}
    assert all(m.higher_is_better for m in (CitationPrecision(), CitationRecall(), CitationF1()))
