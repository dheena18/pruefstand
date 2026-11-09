"""``Runner``: all cases concurrently against a ``TargetAdapter`` (interfaces §8, T1.8)."""

import asyncio
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np

from pruefstand.core.config import RunnerConfig
from pruefstand.core.errors import BudgetExceeded
from pruefstand.core.logging import get_logger
from pruefstand.core.models.metric import MetricKind, MetricStatus, MetricValue
from pruefstand.core.models.run import RunResults, ScoredCase
from pruefstand.core.models.target import CaseRecord
from pruefstand.core.models.testcase import TestCase
from pruefstand.core.protocols import JudgePoolLike, KVCache, TargetAdapter
from pruefstand.llm.budget import Budget, ChargeTally, tally_charges
from pruefstand.metrics.judged.consistency import BaseAnswers, base_answers
from pruefstand.metrics.registry import MetricRegistry
from pruefstand.runner.judging import JudgeScope, JudgeStage
from pruefstand.runner.manifest import RunEnd, RunFacts, StopReason, build_manifest
from pruefstand.runner.refusal import finalise_refusal
from pruefstand.runner.routing import Route, route_case
from pruefstand.runner.scoring import deterministic_values
from pruefstand.runner.target_call import TargetCaller
from pruefstand.store.artifacts import new_run_id

_log = get_logger(__name__)


@dataclass(frozen=True)
class _Done:
    """A finished case: its record, its scored values and the counters it caused."""

    record: CaseRecord
    scored: ScoredCase
    counts: Counter[str]
    judged: bool


class Runner:
    """Runs test cases against a target, scores them and stops cleanly on budget or abort.

    Args:
        adapter: The system under test.
        metrics: The metric registry.
        judges: Judge pool, or None (judged metrics are then ``not_applicable``).
        cache: Optional target-response cache (namespace ``target``); the runner never caches
            judge results (that is ``LLMClient``'s job).
        budget: Run budget, charged only by LLM calls (judged metrics).
        cfg: Concurrency, timeout and retry settings.
        hard_fail: Metrics whose value 1 keeps a case away from the judges.
        judge_scope: Which cases the judges may see (selected ids of a capped run, canaries).
    """

    def __init__(  # noqa: PLR0917  (signature fixed by interfaces §8, X4.1)
        self,
        adapter: TargetAdapter,
        metrics: MetricRegistry,
        judges: JudgePoolLike | None,
        cache: KVCache | None,
        budget: Budget,
        cfg: RunnerConfig,
        *,
        hard_fail: tuple[str, ...] = ("canary_leak", "tenant_leak", "system_prompt_leak"),
        judge_scope: JudgeScope | None = None,
    ) -> None:
        self._metrics = metrics
        self._judges = judges
        self._budget = budget
        self._cfg = cfg
        self._hard_fail = hard_fail
        self._scope = judge_scope
        self._caller = TargetCaller(adapter, cache, cfg)

    async def run(
        self,
        cases: Sequence[TestCase],
        *,
        target_fingerprint: str,
        seed: int,
        judged_subset: bool = False,
    ) -> RunResults:
        """Execute ``cases`` and return the results in input order.

        A target error or timeout (after retries) is recorded, never dropped: the case gets
        ``error_rate = 1`` and ``error`` values. ``BudgetExceeded`` stops the run
        (``stop_reason="budget_exceeded"``); cancellation or ``KeyboardInterrupt`` ends it as
        ``"aborted"`` with ``infra_error`` unset. Finished cases are always kept. Note that the
        cancellation is absorbed here: ``run`` returns the aborted results instead of raising.

        Args:
            cases: The cases to run.
            target_fingerprint: Fingerprint of the target (part of the cache key).
            seed: Run seed (retry jitter).
            judged_subset: Judged metrics only on ``TestCase.judged_subset`` cases; ``core``
                answerable cases outside it are retrieved, not generated (R13 P3.4).

        Returns:
            Results whose manifest holds only what the runner knows; the pipeline completes it.

        Raises:
            PruefstandError: Subclass for an unexpected failure inside a case (a bug); the
                remaining cases are cancelled first.
        """
        started, created_at = time.perf_counter(), datetime.now(UTC)
        facts = RunFacts(
            run_id=new_run_id(created_at),
            created_at=created_at,
            cases=tuple(cases),
            target_fingerprint=target_fingerprint,
            seed=seed,
            judged_subset=judged_subset,
            judges_given=self._judges is not None,
        )
        stage = JudgeStage(self._metrics, self._judges, self._budget, self._hard_fail, self._scope)
        slots: list[_Done | None] = [None] * len(cases)
        semaphore = asyncio.Semaphore(self._cfg.concurrency)
        # bases start before their perturbed variants, which wait for the base answer
        order = sorted(range(len(cases)), key=lambda i: cases[i].perturbation is not None)
        bases = [str(c.id) for c in cases if c.perturbation is None]
        with tally_charges() as cost, base_answers(bases) as answers:

            async def one(index: int) -> None:
                async with semaphore:
                    slots[index] = await self._case(index, cases[index], stage, facts, answers)

            stop = await _drive([asyncio.create_task(one(i)) for i in order])
        done = [d for d in slots if d is not None]
        return self._results(facts, done, cost, stop, time.perf_counter() - started)

    def _results(
        self, facts: RunFacts, done: list[_Done], cost: ChargeTally, stop: StopReason, secs: float
    ) -> RunResults:
        counts: Counter[str] = Counter()
        for item in done:
            counts.update(item.counts)
        end = RunEnd(cost, secs, counts, stop, sum(d.judged for d in done))
        return RunResults(
            manifest=build_manifest(facts, end, self._metrics),
            records=tuple(d.record for d in done),
            values=tuple(d.scored for d in done),
        )

    async def _case(
        self, index: int, case: TestCase, stage: JudgeStage, facts: RunFacts, answers: BaseAnswers
    ) -> _Done:
        route = route_case(case, judged_subset=facts.judged_subset)
        rng = case_rng(facts.seed, index)
        try:
            fetched = await self._caller.fetch(
                case, route, target_fingerprint=facts.target_fingerprint, rng=rng
            )
        except BaseException:
            answers.resolve(str(case.id), None)  # never leave a variant waiting
            raise
        record = fetched.record
        reply = record.response
        answers.resolve(str(case.id), reply.answer if reply and record.mode == "answer" else None)
        # After a fallback to /v1/query the answer metrics apply; judging keeps the original route.
        scoring_route = route if record.mode == "retrieve" else Route("answer", None)
        # Synchronous on purpose: metrics share a wall-clock regex budget (REGEX_TIMEOUT_S).
        values = deterministic_values(case, record, scoring_route, self._metrics)
        judged = await stage.judge(case, record, route, values, judged_subset=facts.judged_subset)
        values = finalise_refusal(case, values, judged.values)
        values.update(judged.values)
        ordered = tuple(values[m.name] for m in self._metrics.all())
        counts = _case_counts(record, ordered, self._metrics)
        counts.update(judged.counts)
        if fetched.fallback:
            counts["retrieve_fallback"] += 1
        return _Done(record, ScoredCase(case=case, values=ordered), counts, judged.attempted)


def case_rng(seed: int, index: int) -> np.random.Generator:
    """Return the jitter generator of case ``index``; seeds 5 and -5 give different streams."""
    return np.random.default_rng([seed % 2**64, index])


def _case_counts(
    record: CaseRecord, values: tuple[MetricValue, ...], registry: MetricRegistry
) -> Counter[str]:
    counts: Counter[str] = Counter()
    counts["error" if record.error is not None else "ok"] += 1
    counts["cached"] += record.cached
    counts["retrieve"] += record.mode == "retrieve"
    judged_names = {m.name for m in registry.all() if m.kind is MetricKind.JUDGED}
    for value in values:
        counts["not_applicable"] += value.status is MetricStatus.NOT_APPLICABLE
        too_long = value.details.get("reason") == "judge_input_too_long"
        if too_long and value.metric in judged_names:
            counts["judge_truncated"] += 1  # estimate path and provider-reported cut alike
        if value.details.get("truncated") is True:
            key = "judge_truncated" if value.metric in judged_names else "metric_truncated"
            counts[key] += 1
            _log.warning("metric_input_truncated", case_id=record.case_id, metric=value.metric)
    flagged = (v.details.get("refusal_flag_mismatch") for v in values)
    counts["refusal_flag_mismatch"] += any(isinstance(f, int | float) and f for f in flagged)
    return counts


async def _drive(tasks: list["asyncio.Task[None]"]) -> StopReason:
    """Wait for the case tasks; on the first failure or on cancellation stop the rest.

    Cancellation of the awaiting task is deliberately *absorbed* (and ``uncancel``led): the spec
    wants an ``aborted`` run that keeps the finished cases, not a ``CancelledError`` that loses
    them. Callers that need to propagate the cancellation must check ``stop_reason``.
    """
    stop: StopReason = "completed"
    if not tasks:
        return stop
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
    except (asyncio.CancelledError, KeyboardInterrupt):
        stop = "aborted"
        current = asyncio.current_task()
        if current is not None:
            current.uncancel()
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    failures = [t.exception() for t in tasks if t.done() and not t.cancelled() and t.exception()]
    unexpected = [e for e in failures if e is not None and not isinstance(e, BudgetExceeded)]
    if unexpected:
        raise unexpected[0]
    if failures and stop == "completed":
        stop = "budget_exceeded"
    return stop
