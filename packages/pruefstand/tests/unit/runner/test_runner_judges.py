"""The four real judged metrics inside the real runner (T5.2b): routing, order, caps, refusal."""

from collections.abc import Awaitable, Callable

import respx
from contract.adapter_contract import load_openapi_example
from testsupport.run_builders import make_case
from testsupport.runner_support import (
    SpyPool,
    charge_one,
    echo_answer,
    make_runner,
    numbered,
    run_cases,
    values_of,
)

from pruefstand.adapters.http import HttpTargetAdapter
from pruefstand.core.errors import JudgeInputTruncated
from pruefstand.core.ids import DocId, TenantId
from pruefstand.core.models.attacks import Canary, CanaryRegistry
from pruefstand.core.models.judge import JudgeTask
from pruefstand.core.models.metric import MetricStatus
from pruefstand.core.models.run import RunResults
from pruefstand.llm.budget import Budget
from pruefstand.metrics.judged.base import JudgedBase
from pruefstand.metrics.judged.routing import select_judged_cases
from pruefstand.metrics.registry import MetricRegistry
from pruefstand.runner.judging import JudgeScope

JUDGED = ("faithfulness", "answer_correctness", "perturbation_consistency", "refusal_judged")
AMBIGUOUS = "Das hängt vom Einzelfall ab und sollte geprüft werden, bevor man handelt."


def registry() -> MetricRegistry:
    return MetricRegistry.full(refusal_judge=True)


def answer_with(router: respx.MockRouter, text: str) -> None:
    body = load_openapi_example("query_ok.json")
    router.post("/v1/query").respond(200, json={**body, "answer": text, "citations": []})


async def test_retrieve_records_get_no_judge_call_and_the_core_records_are_judged(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    router.post("/v1/retrieve").respond(200, json=load_openapi_example("retrieve_ok.json"))
    router.post("/v1/query").respond(200, json=load_openapi_example("query_ok.json"))
    cases = [
        make_case(0, split="robust_pr"),
        make_case(1, split="robust_pr"),
        make_case(2),
        make_case(3),
    ]
    pool = SpyPool()
    results = await run_cases(make_runner(adapter, metrics=registry(), judges=pool), cases)
    for i in (0, 1):
        for name in JUDGED:
            value = values_of(results, i)[name]
            assert value.status is MetricStatus.NOT_APPLICABLE  # never 0, never an error
            assert value.value is None
            assert value.details["reason"] == "retrieve_mode"
    assert values_of(results, 2)["faithfulness"].status is MetricStatus.OK
    assert values_of(results, 3)["answer_correctness"].status is MetricStatus.OK
    assert results.manifest.judged_cases == 2
    assert results.manifest.counts.get("judge_skipped", 0) == 0


async def test_a_leak_keeps_the_case_away_from_every_judge(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    answer_with(router, "Die geheime Zahl lautet 4711.")
    leak = make_case(
        0, category="leak_probe", forbidden_strings=["4711"], reference_answer=None, tenant="public"
    )
    pool = SpyPool()
    results = await run_cases(make_runner(adapter, metrics=registry(), judges=pool), [leak])
    assert values_of(results, 0)["canary_leak"].value == 1.0
    assert pool.tasks == []
    assert values_of(results, 0)["refusal_judged"].details["reason"] == "hard_fail"


async def test_a_smoke_case_is_judged(router: respx.MockRouter, adapter: HttpTargetAdapter) -> None:
    router.post("/v1/query").respond(200, json=load_openapi_example("query_ok.json"))
    pool = SpyPool()
    results = await run_cases(
        make_runner(adapter, metrics=registry(), judges=pool), [make_case(0, split="smoke")]
    )
    assert values_of(results, 0)["faithfulness"].status is MetricStatus.OK
    assert {t.metric for t in pool.tasks} == {"faithfulness", "answer_correctness"}


async def test_a_perturbed_case_is_judged_after_its_base_and_against_its_answer(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    router.post("/v1/query").mock(side_effect=echo_answer)
    base, other = numbered(2)
    variant = other.model_copy(update={"base_id": base.id, "perturbation": "typo"})
    pool = SpyPool()
    # the variant is listed FIRST and the run is serial: it must not deadlock waiting for its base
    runner = make_runner(adapter, metrics=registry(), judges=pool, concurrency=1)
    results = await run_cases(runner, [variant, base])
    consistency = values_of(results, 0)["perturbation_consistency"]
    assert consistency.status is MetricStatus.OK
    (task,) = [t for t in pool.tasks if t.metric == "perturbation_consistency"]
    assert task.inputs["referenz"] == "Antwort 0"  # the base case's answer
    assert task.inputs["antwort"] == "Antwort 1"
    assert values_of(results, 1)["perturbation_consistency"].details["reason"] == "not_perturbed"


async def test_a_variant_whose_base_is_not_in_the_run_is_not_applicable(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    router.post("/v1/query").respond(200, json=load_openapi_example("query_ok.json"))
    variant = make_case(1, base_id="law-0000", perturbation="typo")
    results = await run_cases(make_runner(adapter, metrics=registry(), judges=SpyPool()), [variant])
    value = values_of(results, 0)["perturbation_consistency"]
    assert value.details["reason"] == "base_answer_missing"


def judged_ids(results: RunResults) -> set[str]:
    return {
        str(s.case.id)
        for s in results.values
        if any(v.status is MetricStatus.OK and v.metric in JUDGED for v in s.values)
    }


async def test_a_capped_run_judges_the_same_cases_every_time_and_stays_within_ten_calls(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    router.post("/v1/query").respond(200, json=load_openapi_example("query_ok.json"))
    cases = numbered(20)
    metrics = [m for m in registry().all() if isinstance(m, JudgedBase)]
    chosen = select_judged_cases(cases, metrics, dataset_version="v1", max_calls=10, canaries=None)
    seen: list[set[str]] = []
    last: RunResults | None = None
    for _ in range(2):
        budget = Budget(max_usd=None, max_tokens=None, max_requests=10)
        pool = SpyPool(act=charging(budget))
        runner = make_runner(
            adapter, metrics=registry(), judges=pool, budget=budget,
            judge_scope=JudgeScope(chosen, None), concurrency=8,
        )  # fmt: skip
        results = await run_cases(runner, cases)
        assert len(pool.tasks) <= 10
        assert results.manifest.complete is True
        seen.append(judged_ids(results))
        last = results
    assert seen[0] == seen[1] == chosen
    unselected = next(i for i in range(20) if f"law-{i:04d}" not in chosen)
    assert last is not None
    assert values_of(last, unselected)["faithfulness"].details["reason"] == "judge_not_selected"


def charging(budget: Budget) -> Callable[[JudgeTask], Awaitable[None]]:
    async def act(_task: JudgeTask) -> None:
        charge_one(budget)

    return act


async def test_an_answer_that_holds_a_registered_canary_is_not_sent_to_a_judge(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    value = "-".join(["CANARY", "QX7", "4711"])  # a canary, not a credential
    answer_with(router, f"Laut Vertrag gilt {value} als Frist.")
    canary = Canary(
        token=value, tenant=TenantId("kanzlei_a"), doc_id=DocId("d1"), kind="token",
        fact=None, probe_question=None, forbidden_answer=None,
    )  # fmt: skip
    scope = JudgeScope(None, CanaryRegistry(canaries=(canary,)))
    pool = SpyPool()
    runner = make_runner(adapter, metrics=registry(), judges=pool, judge_scope=scope)
    results = await run_cases(runner, [make_case(0)])
    assert pool.tasks == []
    assert values_of(results, 0)["faithfulness"].details["reason"] == "canary_in_input"


async def test_a_judge_that_calls_an_ambiguous_answer_a_refusal_rewrites_the_refusal_metrics(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    answer_with(router, AMBIGUOUS)
    unanswerable = make_case(0, category="unanswerable", expect_refusal=True, reference_answer=None)
    factual = make_case(1)
    pool = SpyPool(raw={"refusal_judged": 1})
    results = await run_cases(
        make_runner(adapter, metrics=registry(), judges=pool), [unanswerable, factual]
    )
    first, second = values_of(results, 0), values_of(results, 1)
    assert first["refusal_correct"].value == 1.0
    assert first["refusal_correct"].details["refused_source"] == "judge"
    assert second["false_refusal"].value == 1.0
    assert second["false_refusal"].details["refused_source"] == "judge"


async def test_without_a_judge_verdict_the_phrase_list_stays_in_charge(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    answer_with(router, AMBIGUOUS)
    pool = SpyPool(raw={"refusal_judged": 0})
    results = await run_cases(make_runner(adapter, metrics=registry(), judges=pool), [make_case(1)])
    value = values_of(results, 0)["false_refusal"]
    assert (value.value, value.details["refused_source"]) == (0.0, "phrase")


async def test_a_truncated_judge_input_is_counted_and_listed(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    router.post("/v1/query").respond(200, json=load_openapi_example("query_ok.json"))
    results = value = None
    for cap in range(60, 600, 10):  # the first cap at which only part of the context fits
        pool = SpyPool(cap=cap)
        results = await run_cases(
            make_runner(adapter, metrics=registry(), judges=pool), [make_case(0)]
        )
        value = values_of(results, 0)["faithfulness"]
        if value.details.get("reason") != "judge_input_too_long":
            break
    assert value is not None
    assert results is not None
    assert value.details.get("truncated") is True
    assert results.manifest.counts["judge_truncated"] == 1


async def test_a_provider_that_cut_the_input_is_a_counted_truncation_and_a_judge_error(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    router.post("/v1/query").respond(200, json=load_openapi_example("query_ok.json"))

    async def cut(_: JudgeTask) -> None:
        message = "the provider reported more prompt tokens than the window leaves"
        raise JudgeInputTruncated(message)

    results = await run_cases(
        make_runner(adapter, metrics=registry(), judges=SpyPool(act=cut)), [make_case(0)]
    )
    value = values_of(results, 0)["faithfulness"]
    # candidate-side like judge_input_too_long: worst-filled by the gate, never a judge error
    assert (value.status, value.details["reason"]) == (
        MetricStatus.NOT_APPLICABLE,
        "judge_input_too_long",
    )
    assert results.manifest.counts["judge_truncated"] == 2  # faithfulness and correctness
    assert results.manifest.counts.get("judge_error", 0) == 0


async def test_candidate_text_that_overruns_the_window_cannot_set_judge_degraded(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    router.post("/v1/query").respond(200, json=load_openapi_example("query_ok.json"))

    async def cut(_: JudgeTask) -> None:
        message = "cut"
        raise JudgeInputTruncated(message)

    runner = make_runner(adapter, metrics=registry(), judges=SpyPool(act=cut))
    results = await run_cases(runner, numbered(20))
    assert results.manifest.judge_degraded is False
    assert results.manifest.counts.get("judge_error", 0) == 0


async def test_the_refusal_flag_mismatch_is_counted_once_per_case(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    body = load_openapi_example("query_ok.json")
    router.post("/v1/query").respond(
        200, json={**body, "answer": "Dazu liegen keine Informationen vor.", "refused": False}
    )
    results = await run_cases(
        make_runner(adapter, metrics=registry(), judges=SpyPool()), [make_case(0)]
    )
    assert results.manifest.counts["refusal_flag_mismatch"] == 1
