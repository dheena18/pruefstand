import asyncio
from pathlib import Path

import pytest
from testsupport.judged_support import failing, judges, response, user_prompts, verdict
from testsupport.run_builders import make_case

from pruefstand.core.errors import LLMError
from pruefstand.core.models.metric import MetricStatus
from pruefstand.llm import retry
from pruefstand.metrics.judged.consistency import PerturbationConsistency, base_answers


async def test_an_unperturbed_case_is_not_applicable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with judges(tmp_path, monkeypatch, []) as (pool, state, _):
        value = await PerturbationConsistency().acompute(make_case(0), response(), pool)
    assert value.details["reason"] == "not_perturbed"
    assert user_prompts(state) == []


async def test_a_variant_without_a_base_answer_in_the_run_is_not_applicable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with judges(tmp_path, monkeypatch, []) as (pool, state, _):
        value = await PerturbationConsistency().acompute(
            make_case(1, base_id="law-0000", perturbation="typo"), response(), pool
        )
        with base_answers(["law-0000"]) as answers:
            answers.resolve("law-0000", None)  # the base case produced no answer
            again = await PerturbationConsistency().acompute(
                make_case(1, base_id="law-0000", perturbation="typo"), response(), pool
            )
    assert value.details["reason"] == again.details["reason"] == "base_answer_missing"
    assert user_prompts(state) == []


async def test_raw_one_is_one_and_the_base_answer_is_the_reference_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = make_case(1, base_id="law-0000", perturbation="typo")
    with (
        judges(tmp_path, monkeypatch, [verdict(1)]) as (pool, state, _),
        base_answers(["law-0000"]) as answers,
    ):
        answers.resolve("law-0000", "Vier Wochen zum Monatsende.")
        value = await PerturbationConsistency().acompute(case, response("4 Wochen."), pool)
    (prompt,) = user_prompts(state)
    assert (value.status, value.value) == (MetricStatus.OK, 1.0)
    assert "Vier Wochen zum Monatsende." in prompt
    assert "4 Wochen." in prompt


async def test_a_variant_waits_for_its_base_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = make_case(1, base_id="law-0000", perturbation="typo")
    with (
        judges(tmp_path, monkeypatch, [verdict(1)]) as (pool, state, _),
        base_answers(["law-0000"]) as answers,
    ):
        task = asyncio.create_task(PerturbationConsistency().acompute(case, response("x"), pool))
        await asyncio.sleep(0.05)
        assert not task.done()
        assert user_prompts(state) == []
        answers.resolve("law-0000", "Basisantwort.")
        value = await task
    assert value.status is MetricStatus.OK


async def test_a_judge_failure_raises_llm_error_for_the_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def no_wait(_: float) -> None:
        return None

    monkeypatch.setattr(retry, "pause", no_wait)
    case = make_case(1, base_id="law-0000", perturbation="typo")
    with (
        judges(tmp_path, monkeypatch, [failing(503)] * 8) as (pool, _, _),
        base_answers(["law-0000"]) as answers,
    ):
        answers.resolve("law-0000", "Basisantwort.")
        with pytest.raises(LLMError):
            await PerturbationConsistency().acompute(case, response("x"), pool)
