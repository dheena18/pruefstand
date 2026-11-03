"""Run the injection robustness set against a real ``Judge`` (gpu and live tests)."""

import asyncio
from collections.abc import Sequence
from pathlib import Path

from pruefstand.judges.judge import Judge
from pruefstand.judges.output import make_task
from pruefstand.judges.robustness import InjectionItem, RobustnessResult, summarize, task_inputs

SET = Path(__file__).resolve().parents[4] / "datasets" / "fixtures" / "judge_injection.jsonl"
CONCURRENCY = 4


async def shifts_for(judge: Judge, metric: str, items: Sequence[InjectionItem]) -> RobustnessResult:
    """Score every item clean and injected with ``judge`` and return the shift summary."""
    gate = asyncio.Semaphore(CONCURRENCY)

    async def score(item: InjectionItem, *, injected: bool) -> float:
        async with gate:
            inputs = task_inputs(metric, item, injected=injected)
            return (await judge.score(make_task(metric, **inputs))).score

    clean = await asyncio.gather(*(score(i, injected=False) for i in items))
    dirty = await asyncio.gather(*(score(i, injected=True) for i in items))
    return summarize(clean, dirty)
