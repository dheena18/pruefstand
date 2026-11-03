"""Cut and too-long judge inputs are candidate-side and keep the judged-case denominator."""

import respx
from contract.adapter_contract import load_openapi_example
from testsupport.run_builders import make_case
from testsupport.runner_support import SpyPool, make_runner, numbered, run_cases, values_of

from pruefstand.adapters.http import HttpTargetAdapter
from pruefstand.core.errors import JudgeInputTruncated, LLMError
from pruefstand.core.models.judge import JudgeTask
from pruefstand.metrics.registry import MetricRegistry
from pruefstand.pipeline.judge_mode import final_judge_mode


def registry() -> MetricRegistry:
    return MetricRegistry.full(refusal_judge=True)


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


async def test_all_cases_cut_by_the_window_still_count_as_judged(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    router.post("/v1/query").respond(200, json=load_openapi_example("query_ok.json"))

    async def cut(_: JudgeTask) -> None:
        message = "cut"
        raise JudgeInputTruncated(message)

    runner = make_runner(adapter, metrics=registry(), judges=SpyPool(act=cut))
    results = await run_cases(runner, numbered(20))
    assert results.manifest.judged_cases == 20  # not 0: that would switch the judge mode off
    assert final_judge_mode("local", judged_cases=results.manifest.judged_cases) == "local"


async def test_all_cases_too_long_by_the_estimate_still_count_as_judged(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    router.post("/v1/query").respond(200, json=load_openapi_example("query_ok.json"))
    runner = make_runner(adapter, metrics=registry(), judges=SpyPool(cap=1))
    results = await run_cases(runner, numbered(20))
    assert values_of(results, 0)["faithfulness"].details["reason"] == "judge_input_too_long"
    assert results.manifest.judged_cases == 20
    assert final_judge_mode("local", judged_cases=results.manifest.judged_cases) == "local"


async def test_cut_cases_keep_the_denominator_of_the_judge_error_share(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    router.post("/v1/query").respond(200, json=load_openapi_example("query_ok.json"))

    async def act(task: JudgeTask) -> None:
        if task.inputs["frage"].startswith("Frage 0:"):
            if task.metric == "faithfulness":
                message = "judge down"
                raise LLMError(message, transient=True)
            return
        message = "cut"
        raise JudgeInputTruncated(message)

    runner = make_runner(adapter, metrics=registry(), judges=SpyPool(act=act))
    results = await run_cases(runner, numbered(20))
    assert results.manifest.counts["judge_error"] == 1
    assert results.manifest.judged_cases == 20
    assert results.manifest.judge_degraded is False  # 1 error in 20 judged cases is 5 %, not more
