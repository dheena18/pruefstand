"""CLI of the model benchmark (T3.1b S2): phases on the resident models, redacted CSV/JSONL.

Run it under the GPU lock only (``make bench-models``); it refuses to start without
``PRUEFSTAND_LOCK_HELD=1`` or when the resident set differs from the day set. Phases: quality,
throughput, parallel, json, kv, longctx, vram.

    PYTHONPATH=experiments python -m model_selection.bench --phases quality,json --date 2026-11-02
"""

import argparse
import csv
import json
import os
import sys
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

from model_selection import bench_runs as runs
from model_selection import stats, vram
from model_selection.bench_cases import CASES_PATH, Case, load_cases
from model_selection.client import BenchError, OllamaClient, load_entry

RESULTS = Path(__file__).resolve().parent / "results"
GEN_ID, JUDGE_ID, EMBED_ID = "ollama/qwen3.8:27b-q8_0", "ollama/gemma3:12b", "ollama/bge-m3"
DAY_SET = {"qwen3.8:27b-q8_0", "bge-m3", "gemma3:12b"}
PHASES = ("quality", "throughput", "parallel", "json", "vram", "kv", "longctx")
FIELDS = ("run_id", "date", "phase", "model", "concurrency", "metric", "value")


def long_pool(cases: list[Case]) -> list[str]:
    """Distinct law texts used to build long prompts."""
    return sorted({c.context for c in cases if c.context and c.kind == "law_qa"})


def flatten(run_id: str, day: str, phase: str, row: dict[str, Any]) -> Iterable[tuple[Any, ...]]:
    """One CSV tuple per metric of a result row; ``model`` and ``concurrency`` are columns."""
    for key, val in row.items():
        if key not in ("model", "concurrency"):
            yield (run_id, day, phase, row.get("model", ""), row.get("concurrency", ""), key, val)


def preflight(c0: OllamaClient) -> None:
    """Refuse to run outside the GPU lock or when anything but the day set is resident."""
    if os.environ.get("PRUEFSTAND_LOCK_HELD") != "1":
        msg = "run under the GPU lock: make bench-models (pruefstand-lock)"
        raise SystemExit(msg)
    resident = {m["name"].removesuffix(":latest") for m in c0.get("ps")["models"]}
    if resident != DAY_SET:
        msg = f"resident set {sorted(resident)} is not the day set; use make gpu-up first"
        raise SystemExit(msg)


def phase_quality(ctx: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """German smoke on the generator and the judge model; returns (summary rows, answer rows)."""
    summary, answers = [], []
    for entry, client in ((ctx["gen"], ctx["c0"]), (ctx["judge"], ctx["c1"])):
        rows = runs.quality_run(client, entry, ctx["cases"])
        answers += rows
        scores = [r["score"] for r in rows]
        mean, lo, hi = stats.bootstrap_ci(scores, seed=42)
        summary.append(
            {
                "model": entry.id,
                "n": len(rows),
                "reloads": sum(r["load_s"] > runs.RELOAD_S for r in rows),
                "score_mean": round(mean, 3),
                "ci_lo": round(lo, 3),
                "ci_hi": round(hi, 3),
                "think_answers": sum("<think>" in r["answer"] for r in rows),
            }
        )
        for kind in sorted({r["kind"] for r in rows}):
            ks = [r["score"] for r in rows if r["kind"] == kind]
            summary.append(
                {
                    "model": entry.id,
                    "kind": kind,
                    "n": len(ks),
                    "score_mean": round(sum(ks) / len(ks), 3),
                }
            )
    return summary, answers


def phase_throughput(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    """Concurrency 1/4/8 for the generator and the judge, one after the other."""
    out = []
    for entry, client in ((ctx["gen"], ctx["c0"]), (ctx["judge"], ctx["c1"])):
        out.append({"model": entry.id, "first_call_load_s": runs.warm_up(client, entry)})
        out += [
            runs.throughput_run(client, entry, ctx["pool"], c, calls)
            for c, calls in ((1, 3), (4, 8), (8, 16))
        ]
    return out


def phase_parallel(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    """Generator and judge at the same time, 4 streams each.

    (the PR tier and the nightly pipeline them).
    """
    with ThreadPoolExecutor(max_workers=2) as pool:
        futs = [
            pool.submit(runs.throughput_run, cl, en, ctx["pool"], 4, 8)
            for en, cl in ((ctx["gen"], ctx["c0"]), (ctx["judge"], ctx["c1"]))
        ]
        rows = [f.result() for f in futs]
    return [{**r, "mode": "generator_and_judge_simultaneous"} for r in rows]


def phase_kv(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    """Resident size at several ``num_ctx`` for the judge and the generator.

    Restores the catalogue options.
    """
    out: list[dict[str, Any]] = []
    for entry, client in ((ctx["judge"], ctx["c1"]), (ctx["gen"], ctx["c0"])):
        try:
            rows = runs.kv_run(client, entry, [4096, 8192, 12288, 16384])
        finally:
            runs.warm_up(client, entry)  # reloads with exactly the catalogue options
        out += rows
        out.append(
            {
                "model": entry.id,
                "kv_bytes_per_token_if_4_slots": round(runs.kv_bytes_per_token(rows, 4)),
                "kv_bytes_per_token_if_1_slot": round(runs.kv_bytes_per_token(rows, 1)),
                "kv_reliable": 0,
                "restored_num_ctx": runs.ps_entry(client, entry.tag).get("context_length", 0),
            }
        )
    return out


def phase_json(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    """Judge JSON validity over 50 calls and the rubric allowance."""
    row = runs.json_run(ctx["c1"], ctx["judge"], ctx["cases"])
    return [
        row,
        {
            "model": ctx["judge"].id,
            "allowance_tokens_max": runs.allowance_run(ctx["c1"], ctx["judge"], ctx["cases"]),
        },
    ]


def run(phases: list[str], day: str, out_dir: Path) -> None:
    """Execute ``phases`` and write ``<day>.csv`` and ``<day>_answers.jsonl``.

    (redacted) into ``out_dir``.
    """
    run_id = datetime.now().astimezone().strftime("%Y-%m-%dT%H%M")
    cases = load_cases(CASES_PATH)
    c0, c1 = OllamaClient(lane="GPU0"), OllamaClient(lane="GPU1")
    preflight(c0)
    ctx: dict[str, Any] = {
        "cases": cases,
        "pool": long_pool(cases),
        "c0": c0,
        "c1": c1,
        "gen": load_entry(GEN_ID),
        "judge": load_entry(JUDGE_ID),
    }
    rows: list[tuple[Any, ...]] = []
    answers: list[dict[str, Any]] = []
    for name in phases:
        if name == "quality":
            summary, answers = phase_quality(ctx)
        elif name == "longctx":
            summary = runs.longctx_run(c1, ctx["judge"], ctx["pool"])
        elif name == "vram":
            summary = [{"model": "cluster", **vram.snapshot()}]
        else:
            summary = {
                "throughput": phase_throughput,
                "parallel": phase_parallel,
                "kv": phase_kv,
                "json": phase_json,
            }[name](ctx)
        for row in summary:
            rows += flatten(run_id, day, name, row)
        print(f"phase {name}: {len(summary)} rows")
    out_dir.mkdir(exist_ok=True)
    write_outputs(out_dir, day, rows, answers)


def write_outputs(
    out_dir: Path, day: str, rows: list[tuple[Any, ...]], answers: list[dict[str, Any]]
) -> None:
    """Write the long-format CSV and the answers JSONL, both passed through ``stats.redact``."""
    with (out_dir / f"{day}.csv").open("a", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        if fh.tell() == 0:
            w.writerow(FIELDS)
        w.writerows([[stats.redact(str(v)) for v in r] for r in rows])
    if answers:
        text = "\n".join(json.dumps(a, ensure_ascii=False) for a in answers) + "\n"
        (out_dir / f"{day}_answers.jsonl").write_text(stats.redact(text), encoding="utf-8")


def main(argv: list[str]) -> int:
    """Entry point; returns the process exit code."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--phases", default=",".join(PHASES), help="comma list of: " + ", ".join(PHASES)
    )
    ap.add_argument("--date", default=datetime.now().astimezone().date().isoformat())
    ap.add_argument("--out-dir", type=Path, default=RESULTS)
    args = ap.parse_args(argv)
    chosen = [p for p in args.phases.split(",") if p]
    unknown = sorted(set(chosen) - set(PHASES))
    if unknown:
        ap.error(f"unknown phases {unknown}")
    try:
        run(chosen, args.date, args.out_dir)
    except BenchError as exc:
        print(f"benchmark stopped: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
