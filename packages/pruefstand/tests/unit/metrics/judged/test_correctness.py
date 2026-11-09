from pathlib import Path

import pytest
from testsupport.judged_support import failing, judges, response, user_prompts, verdict
from testsupport.run_builders import make_case

from pruefstand.core.enums import Category
from pruefstand.core.errors import LLMError
from pruefstand.core.models.metric import MetricStatus
from pruefstand.llm import retry
from pruefstand.metrics.judged.correctness import AnswerCorrectness


async def test_without_a_reference_answer_it_is_not_applicable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with judges(tmp_path, monkeypatch, []) as (pool, state, _):
        value = await AnswerCorrectness().acompute(
            make_case(0, reference_answer=None), response(), pool
        )
    assert (value.status, value.value) == (MetricStatus.NOT_APPLICABLE, None)
    assert user_prompts(state) == []


async def test_raw_one_is_one_half(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with judges(tmp_path, monkeypatch, [verdict(1)]) as (pool, state, _):
        value = await AnswerCorrectness().acompute(make_case(0), response("Vier Wochen."), pool)
    (prompt,) = user_prompts(state)
    assert (value.status, value.value) == (MetricStatus.OK, 0.5)
    reference = make_case(0).reference_answer
    assert reference is not None
    assert reference in prompt  # the reference is a labelled block
    assert "Vier Wochen." in prompt


async def test_a_judge_failure_raises_llm_error_for_the_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def no_wait(_: float) -> None:
        return None

    monkeypatch.setattr(retry, "pause", no_wait)
    with (
        judges(tmp_path, monkeypatch, [failing(503)] * 8) as (pool, _, _),
        pytest.raises(LLMError),
    ):
        await AnswerCorrectness().acompute(make_case(0), response(), pool)


async def test_an_oversized_answer_is_not_cut_and_not_sent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with judges(tmp_path, monkeypatch, []) as (pool, state, _):
        value = await AnswerCorrectness().acompute(make_case(0), response("Wort. " * 4000), pool)
    assert value.details["reason"] == "judge_input_too_long"
    assert user_prompts(state) == []


def test_it_applies_to_answerable_categories_with_a_reference() -> None:
    metric = AnswerCorrectness()
    assert metric.applicable(make_case(0))
    assert not metric.applicable(make_case(0, reference_answer=None))
    assert metric.applies_to == frozenset(
        {Category.FACTUAL, Category.MULTI_HOP, Category.COMPARISON, Category.CROSS_LINGUAL}
    )
