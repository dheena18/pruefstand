"""language_match (T1.5b S6): lingua restricted to DE/EN."""

import unicodedata

from pruefstand.core.models.metric import MetricStatus
from pruefstand.metrics.deterministic.language import LanguageMatch

from testsupport.metric_types import CaseFactory, RespFactory

DE = "Die Kündigungsfrist beträgt einen Monat zum Ende eines Kalendermonats."
EN = "The notice period is one month to the end of a calendar month for the employer."


def test_german_answer_for_german_case(make_case: CaseFactory, make_resp: RespFactory) -> None:
    value = LanguageMatch().compute(make_case(lang="de"), make_resp(DE))
    assert value.status is MetricStatus.OK
    assert value.value == 1.0


def test_german_answer_for_english_case_is_zero(make_case: CaseFactory, make_resp: RespFactory) -> None:
    assert LanguageMatch().compute(make_case(lang="en", question="What is the notice period?"), make_resp(DE)).value == 0.0


def test_english_answer_for_german_case_is_zero(make_case: CaseFactory, make_resp: RespFactory) -> None:
    assert LanguageMatch().compute(make_case(lang="de"), make_resp(EN)).value == 0.0


def test_english_answer_for_english_case(make_case: CaseFactory, make_resp: RespFactory) -> None:
    case = make_case(lang="en", question="What is the notice period?")
    assert LanguageMatch().compute(case, make_resp(EN)).value == 1.0


def test_short_answer_is_not_applicable(make_case: CaseFactory, make_resp: RespFactory) -> None:
    value = LanguageMatch().compute(make_case(), make_resp("Ja."))
    assert value.status is MetricStatus.NOT_APPLICABLE
    assert value.value is None


def test_refusal_is_not_applicable(make_case: CaseFactory, make_resp: RespFactory) -> None:
    resp = make_resp("Die Dokumente enthalten dazu keine Information.")
    assert LanguageMatch().compute(make_case(), resp).status is MetricStatus.NOT_APPLICABLE


def test_nfd_input_is_handled(make_case: CaseFactory, make_resp: RespFactory) -> None:
    resp = make_resp(unicodedata.normalize("NFD", DE))
    assert LanguageMatch().compute(make_case(), resp).value == 1.0


def test_length_is_measured_after_stripping(make_case: CaseFactory, make_resp: RespFactory) -> None:
    assert LanguageMatch().compute(make_case(), make_resp("   Ja.            ")).status is MetricStatus.NOT_APPLICABLE


def test_attributes() -> None:
    assert LanguageMatch().name == "language_match"
    assert LanguageMatch().higher_is_better is True
