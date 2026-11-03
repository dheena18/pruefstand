"""Measurement phases of the model benchmark (T3.1b S2).

Each phase returns plain rows (dicts) that ``bench.py`` writes to CSV/JSONL. Only the resident
models are touched; a request whose ``load_duration`` exceeds 1 s after the warm-up counts as a
reload (AI11-01).
"""

import json
import statistics
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from time import perf_counter
from typing import Any

from model_selection import stats
from model_selection.bench_cases import (
    JUDGE_SCHEMA,
    Case,
    build_messages,
    judge_messages,
    score_case,
)
from model_selection.client import ChatResult, Entry, OllamaClient

Row = dict[str, Any]
RELOAD_S = 1.0
NUM_PARALLEL = 4


def run_concurrent[T](fn: Callable[[int], T], n: int, concurrency: int) -> tuple[list[T], float]:
    """Run ``fn(0..n-1)`` with ``concurrency`` workers.

    Return the results in order and the wall seconds.
    """
    start = perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        results = list(pool.map(fn, range(n)))
    return results, perf_counter() - start


def summarise(results: list[ChatResult], wall_s: float) -> dict[str, float]:
    """Throughput, TTFT, token and reload figures of one concurrent run."""
    per_stream = [stats.tok_per_s(max(r.eval_count - 1, 0), r.wall_s - r.ttft_s) for r in results]
    ttfts = [r.ttft_s for r in results]
    return {
        "n": len(results),
        "wall_s": round(wall_s, 2),
        "decode_tps_per_stream": round(statistics.fmean(per_stream), 2),
        "decode_tps_aggregate": round(
            stats.tok_per_s(sum(r.eval_count for r in results), wall_s), 2
        ),
        "prefill_tps": round(
            statistics.fmean(stats.tok_per_s(r.prompt_eval_count, r.ttft_s) for r in results), 1
        ),
        "ttft_p50_s": round(stats.percentile(ttfts, 50), 3),
        "ttft_p95_s": round(stats.percentile(ttfts, 95), 3),
        "prompt_tokens_mean": round(statistics.fmean(r.prompt_eval_count for r in results), 1),
        "out_tokens_mean": round(statistics.fmean(r.eval_count for r in results), 1),
        "reloads": sum(r.load_duration_s > RELOAD_S for r in results),
        "think_calls": sum(bool(r.thinking) or "<think>" in r.content for r in results),
    }


def warm_up(client: OllamaClient, entry: Entry) -> float:
    """One short call before measuring.

    Returns its load duration (first-load figure if the model was cold).
    """
    return client.chat(entry, [{"role": "user", "content": "Sag kurz Hallo."}]).load_duration_s


def quality_run(
    client: OllamaClient, entry: Entry, cases: list[Case], concurrency: int = NUM_PARALLEL
) -> list[Row]:
    """Answer every German case once.

    Each row carries the answer, the deterministic score and the counts.
    """
    results, _ = run_concurrent(
        lambda i: client.chat(entry, build_messages(cases[i])), len(cases), concurrency
    )
    return [
        {
            "model": entry.id,
            "case": c.id,
            "kind": c.kind,
            "answer": r.content,
            "score": score_case(c, r.content),
            "prompt_eval_count": r.prompt_eval_count,
            "eval_count": r.eval_count,
            "load_s": r.load_duration_s,
        }
        for c, r in zip(cases, results, strict=True)
    ]


def long_text(salt: int, chars: int, pool: list[str]) -> str:
    """A prompt body of about ``chars`` characters from distinct law texts.

    The unique header defeats prefix reuse.
    """
    parts, size, i = [f"Vorgang {salt}-{chars}:"], 0, salt
    while size < chars:
        parts.append(pool[i % len(pool)])
        size += len(parts[-1])
        i += 7
    return "\n\n".join(parts)


def throughput_run(
    client: OllamaClient, entry: Entry, pool: list[str], concurrency: int, calls: int
) -> Row:
    """``calls`` requests of about 3 000 prompt tokens at ``concurrency``.

    Summary of timings and reloads.
    """

    def one(i: int) -> ChatResult:
        text = (
            long_text(i + 100 * concurrency, 10000, pool)
            + "\n\nFasse die Vorschriften in drei Sätzen zusammen."
        )
        return client.chat(entry, [{"role": "user", "content": text}])

    results, wall = run_concurrent(one, calls, concurrency)
    return {"model": entry.id, "concurrency": concurrency, **summarise(results, wall)}


def judge_inputs(cases: list[Case], n: int = 50) -> list[tuple[Case, str, int]]:
    """``n`` judge inputs from law cases.

    The reference answer (expect 1) and another case's answer (expect 0).
    """
    law = [c for c in cases if c.kind == "law_qa"]
    out: list[tuple[Case, str, int]] = []
    for i in range(n // 2):
        out += [(law[i], law[i].ref, 1), (law[i], law[(i + 1) % len(law)].ref, 0)]
    return out


def json_run(
    client: OllamaClient, entry: Entry, cases: list[Case], concurrency: int = NUM_PARALLEL
) -> Row:
    """50 faithfulness-judge calls with the JSON schema.

    Validity rate, verdict accuracy, reloads.
    """
    inputs = judge_inputs(cases)

    def one(i: int) -> ChatResult:
        case, answer, _ = inputs[i]
        return client.chat(
            entry, judge_messages(case.context, case.question, answer), fmt=JUDGE_SCHEMA
        )

    results, wall = run_concurrent(one, len(inputs), concurrency)
    texts = [r.content for r in results]
    hits = sum(
        stats.json_valid(t) and json.loads(t)["score"] == inp[2]
        for t, inp in zip(texts, inputs, strict=True)
    )
    return {
        "model": entry.id,
        "calls": len(texts),
        "json_validity": stats.validity_rate(texts),
        "verdict_accuracy": hits / len(texts),
        **summarise(results, wall),
    }


def allowance_run(client: OllamaClient, entry: Entry, cases: list[Case]) -> int:
    """Rubric + question + answer allowance.

    Max ``prompt_eval_count`` of the judge prompt with an empty context.
    """
    return max(
        client.chat(entry, judge_messages("", c.question, a), fmt=JUDGE_SCHEMA).prompt_eval_count
        for c, a, _ in judge_inputs(cases, 20)
    )


def ps_entry(client: OllamaClient, tag: str) -> dict[str, Any]:
    """The ``/api/ps`` record of ``tag`` (empty when not loaded).

    A ``:latest`` suffix is ignored.
    """
    for m in client.get("ps")["models"]:
        if m["name"].removesuffix(":latest") == tag.removesuffix(":latest"):
            return dict(m)
    return {}


def ps_size(client: OllamaClient, tag: str) -> int:
    """Resident size in bytes of ``tag`` (0 when not loaded)."""
    return int(ps_entry(client, tag).get("size", 0))


def kv_run(client: OllamaClient, entry: Entry, ctxs: list[int]) -> list[Row]:
    """Load ``entry`` at several ``num_ctx`` (reloads it) and record the resident size.

    The caller restores it.
    """
    rows: list[Row] = []
    for ctx in ctxs:
        opts = {**entry.options, "num_ctx": ctx}
        res = client.chat(entry, [{"role": "user", "content": "Sag kurz Hallo."}], options=opts)
        rows.append(
            {
                "model": entry.id,
                "num_ctx": ctx,
                "size_bytes": ps_size(client, entry.tag),
                "load_s": res.load_duration_s,
            }
        )
    return rows


def kv_bytes_per_token(rows: list[Row], slots: int = NUM_PARALLEL) -> float:
    """Slope of resident size over ``num_ctx x slots`` between the smallest and largest context."""
    lo, hi = min(rows, key=lambda r: r["num_ctx"]), max(rows, key=lambda r: r["num_ctx"])
    return float((hi["size_bytes"] - lo["size_bytes"]) / ((hi["num_ctx"] - lo["num_ctx"]) * slots))


def longctx_run(client: OllamaClient, entry: Entry, pool: list[str], n: int = 20) -> list[Row]:
    """Long faithfulness inputs (about 9 500 tokens) at the catalogue ``num_ctx`` and at 16 384.

    Compare counts and verdicts.
    """
    rows: list[Row] = []
    for i in range(n):
        msgs = judge_messages(
            long_text(i, 34000, pool),
            "Was gilt für die Arbeitszeit?",
            "Die Arbeitszeit beträgt acht Stunden.",
        )
        pinned = client.chat(entry, msgs, fmt=JUDGE_SCHEMA)
        wide = client.chat(
            entry, msgs, fmt=JUDGE_SCHEMA, options={**entry.options, "num_ctx": 16384}
        )
        rows.append(
            {
                "model": entry.id,
                "i": i,
                "pinned_prompt_tokens": pinned.prompt_eval_count,
                "wide_prompt_tokens": wide.prompt_eval_count,
                "pinned_verdict": _score(pinned.content),
                "wide_verdict": _score(wide.content),
            }
        )
    return rows


def _score(text: str) -> int | None:
    try:
        return int(json.loads(text)["score"])
    except (ValueError, KeyError, TypeError):
        return None
