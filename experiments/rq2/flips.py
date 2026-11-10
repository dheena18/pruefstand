"""Repeated anchor judging and the flip-rate summary (T5.4 S11, AI13-07)."""

import asyncio
from collections.abc import Sequence

from pruefstand.core.config import LLMPolicyConfig, ModelRef
from pruefstand.judges.anchors import AnchorItem
from pruefstand.judges.drift import drift_threshold, flip_rate
from pruefstand.judges.output import output_model
from pruefstand.llm.budget import Budget
from pruefstand.llm.client import LLMClient
from pruefstand.llm.factory import build_backend
from pruefstand.llm.policy import LLMPolicy
from pruefstand.llm.recorder import CallRecorder

CONCURRENCY = 4  # OLLAMA_NUM_PARALLEL in production


async def judge_anchor_runs(
    rows: Sequence[AnchorItem], repeats: int, judge: str, family: str
) -> list[list[int]]:
    """Judge every anchor ``repeats`` times (cache bypassed, 4 in flight); scores per run."""
    policy = LLMPolicyConfig()
    backend = build_backend(ModelRef(id=judge, family=family), policy=policy)
    client = LLMClient(backend, None, Budget(None, None), CallRecorder(), LLMPolicy(policy))
    gate = asyncio.Semaphore(CONCURRENCY)

    async def one(row: AnchorItem) -> int:
        async with gate:
            out, _ = await client.complete_json_meta(row.request(), output_model(row.metric))
        return out.score

    runs: list[list[int]] = []
    for _ in range(repeats):
        runs.append(list(await asyncio.gather(*(one(r) for r in rows))))
    return runs


def flip_summary(runs: Sequence[Sequence[int]], judge: str) -> dict[str, object]:
    """Flip rate against run 1, its Wilson upper bound, ``a0`` and the drift threshold.

    ``a0`` is the agreement of run 2 with run 1 (the double-judging of N3; recorded only).

    >>> s = flip_summary([[2, 0, 1, 2], [2, 0, 1, 2], [2, 0, 2, 2], [2, 0, 1, 2]], "m")
    >>> s["flips"], s["comparisons"], s["a0"], s["drift_threshold"]
    (1, 12, 1.0, 5)
    """
    first = runs[0]
    n = len(first)
    flips = sum(1 for run in runs[1:] for a, b in zip(first, run, strict=True) if a != b)
    comparisons = n * (len(runs) - 1)
    rate, upper = flip_rate(flips, comparisons)
    a0 = sum(1 for a, b in zip(first, runs[1], strict=True) if a == b) / n
    return {
        "judge": judge,
        "n_anchors": n,
        "repeats": len(runs),
        "flips": flips,
        "comparisons": comparisons,
        "flip_rate": rate,
        "flip_rate_upper": upper,
        "a0": a0,
        "drift_threshold": drift_threshold(upper, n),
        "changed_anchors": sum(1 for i in range(n) if len({run[i] for run in runs}) > 1),
    }
