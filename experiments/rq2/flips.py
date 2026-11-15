"""Repeated anchor judging and the flip-rate summary (T5.4 S11, AI13-07; majority T5.4d)."""

import asyncio
from collections.abc import Sequence

from pruefstand.core.config import LLMPolicyConfig, ModelRef
from pruefstand.judges.anchors import AnchorItem
from pruefstand.judges.drift import count_flips, drift_threshold, flip_rate, majority_scores
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


def _threshold(upper: float, n: int) -> int | None:
    """The judge's drift threshold, None when it is unfit (above the cap, D945)."""
    try:
        return drift_threshold(upper, n)
    except ValueError:
        return None


def flip_summary(
    runs: Sequence[Sequence[int]], judge: str, majority_runs: int = 1
) -> dict[str, object]:
    """Stored verdicts, flip rate, its Wilson upper bound, ``a0`` and the drift threshold.

    ``majority_runs == 1`` (T5.4): the stored verdict is run 1, flips are counted on the later
    runs. ``majority_runs = k > 1`` (T5.4d, D1250): the stored verdict is the majority of runs
    1..k and flips are counted only on the runs after k, so the stored verdict and the flip
    rate come from different runs. ``a0`` is the agreement of the first counted run with the
    stored verdicts (the double-judging of N3; recorded only). Every run's scores are kept.

    >>> s = flip_summary([[2, 0, 1, 2], [2, 0, 1, 2], [2, 0, 2, 2], [2, 0, 1, 2]], "m")
    >>> s["flips"], s["comparisons"], s["a0"], s["drift_threshold"]
    (1, 12, 1.0, 5)
    >>> runs = [[1, 0], [0, 0], [0, 0], [0, 0], [1, 0], [0, 0], [0, 0], [0, 0], [0, 0]]
    >>> s = flip_summary(runs, "m", majority_runs=5)
    >>> s["stored"], s["flips"], s["comparisons"], s["changed_anchors"]
    ([0, 0], 0, 8, 1)
    """
    if not 1 <= majority_runs < len(runs):
        msg = f"need 1 <= majority_runs < {len(runs)} runs (got {majority_runs})"
        raise ValueError(msg)
    stored = majority_scores(runs[:majority_runs])
    counted = runs[majority_runs:]
    n = len(stored)
    flips, comparisons = count_flips(stored, counted)
    rate, upper = flip_rate(flips, comparisons)
    a0 = sum(1 for a, b in zip(stored, counted[0], strict=True) if a == b) / n
    return {
        "judge": judge,
        "n_anchors": n,
        "repeats": len(runs),
        "majority_runs": majority_runs,
        "flips": flips,
        "comparisons": comparisons,
        "flip_rate": rate,
        "flip_rate_upper": upper,
        "a0": a0,
        "drift_threshold": _threshold(upper, n),
        "changed_anchors": sum(1 for i in range(n) if len({run[i] for run in runs}) > 1),
        "stored": stored,
        "runs": [list(run) for run in runs],
    }
