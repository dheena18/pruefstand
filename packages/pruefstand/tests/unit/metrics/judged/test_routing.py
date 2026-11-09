from testsupport.run_builders import make_case, make_cases

from pruefstand.core.ids import DocId, TenantId
from pruefstand.core.models.attacks import Canary, CanaryRegistry
from pruefstand.metrics.judged.correctness import AnswerCorrectness
from pruefstand.metrics.judged.faithfulness import Faithfulness
from pruefstand.metrics.judged.refusal import RefusalJudged
from pruefstand.metrics.judged.routing import (
    case_holds_canary,
    planned_calls,
    select_judged_cases,
)

METRICS = [Faithfulness(), AnswerCorrectness()]
_VALUE = "-".join(["CANARY", "QX7", "4711"])  # built at runtime: a canary, not a credential
CANARY = Canary(
    token=_VALUE, tenant=TenantId("kanzlei_a"), doc_id=DocId("d1"), kind="token",
    fact=None, probe_question=None, forbidden_answer=None,
)  # fmt: skip
REGISTRY = CanaryRegistry(canaries=(CANARY,))


def test_planned_calls_count_the_metrics_that_can_apply() -> None:
    assert planned_calls(make_case(0), METRICS) == 2
    assert planned_calls(make_case(0, reference_answer=None), METRICS) == 1
    unanswerable = make_case(0, category="unanswerable", expect_refusal=True, reference_answer=None)
    assert planned_calls(unanswerable, METRICS) == 0


def test_twenty_cases_with_a_cap_of_ten_judge_at_most_four_cases() -> None:
    cases = make_cases(20)
    chosen = select_judged_cases(cases, METRICS, dataset_version="v1", max_calls=10, canaries=None)
    assert len(chosen) == 4  # 2 calls per case, 9 calls planned (one slot is kept for a repair)


def test_the_selection_depends_on_the_dataset_version_only() -> None:
    cases = make_cases(20)
    a = select_judged_cases(cases, METRICS, dataset_version="v1", max_calls=10, canaries=None)
    again = select_judged_cases(
        list(reversed(cases)), METRICS, dataset_version="v1", max_calls=10, canaries=None
    )
    other = select_judged_cases(cases, METRICS, dataset_version="v2", max_calls=10, canaries=None)
    assert a == again
    assert a != other


def test_a_case_with_a_registered_canary_is_never_selected() -> None:
    leaky = make_case(3, question=f"Was bedeutet {_VALUE} im Vertrag?")
    cases = [leaky, *make_cases(3)[:1], *make_cases(10)[5:]]
    chosen = select_judged_cases(
        cases, METRICS, dataset_version="v1", max_calls=100, canaries=REGISTRY
    )
    assert "law-0003" not in chosen
    assert case_holds_canary(leaky, REGISTRY)
    assert not case_holds_canary(make_case(0), REGISTRY)


def test_probe_cases_are_never_selected() -> None:
    probe = make_case(0, category="leak_probe", forbidden_strings=["x"], reference_answer=None)
    chosen = select_judged_cases(
        [probe], METRICS, dataset_version="v1", max_calls=100, canaries=None
    )
    assert chosen == frozenset()


def test_metrics_whose_meaning_changed_have_a_new_version() -> None:
    assert (Faithfulness().version, RefusalJudged().version) == ("2", "2")
    assert AnswerCorrectness().version == "1"  # unchanged meaning, old baselines stay comparable
