"""Runner test helpers: a real ``HttpTargetAdapter`` under ``respx``, test-only judged metrics."""

import json
import re
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

import httpx
from contract.adapter_contract import load_openapi_example
from testsupport.run_builders import make_case

from pruefstand.adapters.http import HttpTargetAdapter
from pruefstand.core.config import HttpTargetConfig, RunnerConfig
from pruefstand.core.enums import Category
from pruefstand.core.models.judge import JudgeTask, JudgeVerdict
from pruefstand.core.models.llm import LLMResponse
from pruefstand.core.models.metric import MetricKind, MetricStatus, MetricValue
from pruefstand.core.models.run import RunResults
from pruefstand.core.models.target import TargetResponse, Usage
from pruefstand.core.models.testcase import TestCase
from pruefstand.judges.output import SPECS
from pruefstand.judges.tokens import estimate_tokens
from pruefstand.llm.budget import Budget
from pruefstand.metrics.registry import MetricRegistry
from pruefstand.runner.judging import JudgeScope
from pruefstand.runner.runner import Runner

BASE = "http://target.test"


def new_adapter(timeout_s: float = 5) -> HttpTargetAdapter:
    return HttpTargetAdapter(HttpTargetConfig(type="http", url=BASE, timeout_s=timeout_s))


def charge_one(budget: Budget, *, cost_usd: float = 0.0) -> None:
    """Charge one judge request to ``budget`` the way ``LLMClient`` does."""
    budget.charge(
        LLMResponse(
            text="{}",
            model="ollama/gemma3:12b",
            usage=Usage(prompt_tokens=10, completion_tokens=2),
            cost_usd=cost_usd,
            latency_ms=1.0,
            cached=False,
        )
    )


class SpyJudge:
    """A judge that records its calls; ``act`` may charge the budget or raise.

    It answers with the raw score its pool maps to the metric (default 2 = the maximum), so a
    real judged metric and the real runner can be driven without a model.
    """

    def __init__(self, pool: "SpyPool") -> None:
        self._pool = pool

    @property
    def input_cap(self) -> int:
        return self._pool.cap

    def prompt_tokens(self, task: JudgeTask) -> int:
        return sum(estimate_tokens(text) for text in task.inputs.values())

    async def score(self, task: JudgeTask) -> JudgeVerdict:
        self._pool.score_calls.append(task.inputs.get("case_id", ""))
        self._pool.tasks.append(task)
        if self._pool.act is not None:
            await self._pool.act(task)
        top = SPECS[task.metric].max_raw if task.metric in SPECS else 2
        raw = min(self._pool.raw.get(task.metric, top), top)
        return JudgeVerdict(
            score=raw / top,
            reason="ok",
            raw_score=raw,
            judge_model="ollama/gemma3:12b",
            cached=False,
        )


class SpyPool:
    """A ``JudgePoolLike`` that records ``for_metric`` calls (test-only, not a model fake)."""

    def __init__(
        self,
        act: Callable[[JudgeTask], Awaitable[None]] | None = None,
        raw: dict[str, int] | None = None,
        cap: int = 11_264,
    ) -> None:
        self.act = act
        self.cap = cap
        self.raw = raw or {}
        self.for_metric_calls: list[str] = []
        self.score_calls: list[str] = []
        self.tasks: list[JudgeTask] = []

    def for_metric(self, metric: str) -> SpyJudge:
        self.for_metric_calls.append(metric)
        return SpyJudge(self)


class StubJudgedMetric:
    """A test-only judged metric (the default registry has none until T5.2b)."""

    name = "faithfulness"
    version = "1"
    kind = MetricKind.JUDGED
    higher_is_better = True
    requires: frozenset[str] = frozenset()
    applies_to: frozenset[Category] | None = None

    async def acompute(self, case: TestCase, resp: TargetResponse, judges: Any) -> MetricValue:
        task = JudgeTask(
            metric=self.name,
            prompt_id="faithfulness_de",
            prompt_version="1",
            inputs={"case_id": case.id, "frage": case.question},
        )
        verdict = await judges.for_metric(self.name).score(task)
        return MetricValue(
            metric=self.name,
            metric_version=self.version,
            value=verdict.score,
            status=MetricStatus.OK,
        )


def registry_with_judged() -> MetricRegistry:
    return MetricRegistry([*MetricRegistry.default().all(), StubJudgedMetric()])


def make_runner(  # noqa: PLR0913
    adapter: HttpTargetAdapter,
    *,
    metrics: MetricRegistry | None = None,
    judges: SpyPool | None = None,
    cache: Any = None,
    budget: Budget | None = None,
    concurrency: int = 4,
    timeout_s: float = 5,
    max_retries: int = 3,
    backoff_s: float = 0.001,
    hard_fail: tuple[str, ...] | None = None,
    judge_scope: JudgeScope | None = None,
) -> Runner:
    cfg = RunnerConfig(
        concurrency=concurrency, timeout_s=timeout_s, max_retries=max_retries, backoff_s=backoff_s
    )
    extra: dict[str, Any] = {} if hard_fail is None else {"hard_fail": hard_fail}
    extra["judge_scope"] = judge_scope
    return Runner(
        adapter,
        metrics or MetricRegistry.default(),
        judges,
        cache,
        budget or Budget(max_usd=None, max_tokens=None),
        cfg,
        **extra,
    )


async def run_cases(
    runner: Runner, cases: Sequence[TestCase], *, judged_subset: bool = False
) -> RunResults:
    return await runner.run(
        cases, target_fingerprint="fp-test", seed=7, judged_subset=judged_subset
    )


def values_of(results: RunResults, index: int) -> dict[str, MetricValue]:
    return {v.metric: v for v in results.values[index].values}


class DictCache:
    """A real in-memory ``KVCache`` (the protocol is two methods)."""

    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}

    def get(self, key: str) -> bytes | None:
        return self.data.get(key)

    def set(self, key: str, value: bytes) -> None:
        self.data[key] = value


def index_of(request: httpx.Request) -> int:
    match = re.search(r"Frage (\d+)", json.loads(request.content)["question"])
    assert match is not None
    return int(match.group(1))


def numbered(count: int, **changes: Any) -> list[Any]:
    return [make_case(i, question=f"Frage {i}: Kündigungsfrist?", **changes) for i in range(count)]


def echo_answer(request: httpx.Request) -> httpx.Response:
    body = load_openapi_example("query_ok.json")
    return httpx.Response(200, json={**body, "answer": f"Antwort {index_of(request)}"})
