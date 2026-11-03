"""Run the injection robustness set against a real ``Judge`` (gpu and live tests)."""

import asyncio
from collections.abc import Sequence
from pathlib import Path

from pruefstand.judges.judge import Judge
from pruefstand.judges.output import make_task
from pruefstand.judges.robustness import (
    InjectionItem,
    RobustnessResult,
    injection_kind,
    summarize,
    task_inputs,
)

SET = Path(__file__).resolve().parents[4] / "datasets" / "fixtures" / "judge_injection.jsonl"
CONCURRENCY = 4


async def shifts_for(
    judge: Judge, metric: str, items: Sequence[InjectionItem]
) -> tuple[RobustnessResult, list[str]]:
    """Score every item clean and injected with ``judge``.

    Returns:
        The shift summary and one diagnostic line per item (id, side, kind, scores, shift; never
        the injected text).
    """
    gate = asyncio.Semaphore(CONCURRENCY)

    async def score(item: InjectionItem, *, injected: bool) -> float:
        async with gate:
            inputs = task_inputs(metric, item, injected=injected)
            return (await judge.score(make_task(metric, **inputs))).score

    clean = await asyncio.gather(*(score(i, injected=False) for i in items))
    dirty = await asyncio.gather(*(score(i, injected=True) for i in items))
    lines = [
        f"{i.id} {i.side} {injection_kind(i.injection)} clean={c} injected={d} shift={d - c:+.1f}"
        for i, c, d in zip(items, clean, dirty, strict=True)
    ]
    return summarize(clean, dirty), lines
