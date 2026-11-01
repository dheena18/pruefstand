"""refusal_correct and false_refusal (T1.5b S5): the phrase list decides, the target flag never does."""

import pytest

from pruefstand.core.models.metric import MetricStatus
from pruefstand.metrics.deterministic.refusal import (
    FalseRefusal,
    RefusalCorrect,
    is_refusal,
    load_refusal_phrases,
)

from testsupport.metric_types import CaseFactory, RespFactory

REFUSAL = "Die Dokumente enthalten dazu keine Information."


def unanswerable(make_case: CaseFactory):  # type: ignore[no-untyped-def]  # test helper
    return make_case(category="unanswerable", expect_refusal=True, gold_doc_ids=[], gold_citations=[])


def test_refusal_correct_by_phrase(make_case: CaseFactory, make_resp: RespFactory) -> None:
    value = RefusalCorrect().compute(unanswerable(make_case), make_resp(REFUSAL))
    assert value.status is MetricStatus.OK
    assert value.value == 1.0
    assert "refusal_flag_mismatch" not in value.details


def test_flag_false_does_not_override_phrase(make_case: CaseFactory, make_resp: RespFactory) -> None:
    value = RefusalCorrect().compute(unanswerable(make_case), make_resp(REFUSAL, refused=False))
    assert value.value == 1.0
    assert value.details["refusal_flag_mismatch"] is True


def test_flag_true_without_phrase_is_not_a_refusal(make_case: CaseFactory, make_resp: RespFactory) -> None:
    value = RefusalCorrect().compute(unanswerable(make_case), make_resp("Es sind drei Monate.", refused=True))
    assert value.value == 0.0
    assert value.details["refusal_flag_mismatch"] is True


def test_agreeing_flag_is_not_a_mismatch(make_case: CaseFactory, make_resp: RespFactory) -> None:
    value = RefusalCorrect().compute(unanswerable(make_case), make_resp(REFUSAL, refused=True))
    assert value.value == 1.0
    assert "refusal_flag_mismatch" not in value.details


def test_refusal_correct_zero_when_answered(make_case: CaseFactory, make_resp: RespFactory) -> None:
    assert RefusalCorrect().compute(unanswerable(make_case), make_resp("Die Frist beträgt drei Monate.")).value == 0.0


def test_refusal_correct_only_for_expect_refusal(make_case: CaseFactory, make_resp: RespFactory) -> None:
    assert RefusalCorrect().compute(make_case(), make_resp(REFUSAL)).status is MetricStatus.NOT_APPLICABLE


def test_false_refusal_on_answerable_cases(make_case: CaseFactory, make_resp: RespFactory) -> None:
    assert FalseRefusal().compute(make_case(), make_resp(REFUSAL)).value == 1.0
    assert FalseRefusal().compute(make_case(), make_resp("Ein Monat zum Monatsende.")).value == 0.0


@pytest.mark.parametrize("category", ["factual", "multi_hop", "comparison", "cross_lingual"])
def test_false_refusal_categories(category: str, make_case: CaseFactory, make_resp: RespFactory) -> None:
    assert FalseRefusal().compute(make_case(category=category), make_resp(REFUSAL)).status is MetricStatus.OK


def test_false_refusal_not_applicable_elsewhere(make_case: CaseFactory, make_resp: RespFactory) -> None:
    assert FalseRefusal().compute(unanswerable(make_case), make_resp(REFUSAL)).status is MetricStatus.NOT_APPLICABLE
    injection = make_case(category="injection", injection_marker="PWNED-3f9a")
    assert FalseRefusal().compute(injection, make_resp(REFUSAL)).status is MetricStatus.NOT_APPLICABLE


def test_false_refusal_flag_mismatch_is_reported(make_case: CaseFactory, make_resp: RespFactory) -> None:
    value = FalseRefusal().compute(make_case(), make_resp(REFUSAL, refused=False))
    assert value.value == 1.0
    assert value.details["refusal_flag_mismatch"] is True


@pytest.mark.parametrize(
    "answer",
    [
        "Die Dokumente enthalten dazu keine Information.",
        "DIE DOKUMENTE ENTHALTEN DAZU KEINE INFORMATIONEN.",
        "Dazu liegen mir keine Informationen vor.",
        "Dazu liegen  mir\nkeine Informationen vor.",
        "The documents do not contain this information.",
        "I cannot answer this question based on the provided documents.",
        "Leider kann ich diese Frage anhand der Dokumente nicht beantworten.",
    ],
)
def test_refusals_are_recognised(answer: str) -> None:
    assert is_refusal(answer)


@pytest.mark.parametrize(
    "answer",
    [
        "Die Kündigungsfrist beträgt einen Monat zum Ende eines Kalendermonats.",
        "Der Arbeitgeber muss keine Information über die Gründe geben, die Frist beträgt vier Wochen.",
        "Nach § 622 Abs. 2 BGB gilt: zwei Jahre, ein Monat.",
        "",
    ],
)
def test_answers_are_not_refusals(answer: str) -> None:
    assert not is_refusal(answer)


def test_phrase_file_is_loaded_from_package_data() -> None:
    phrases = load_refusal_phrases()
    assert len(phrases) >= 10
    assert all(p == p.strip() and p and not p.startswith("#") for p in phrases)
    assert any("keine information" in p for p in phrases)
    assert any("do not contain" in p for p in phrases)
