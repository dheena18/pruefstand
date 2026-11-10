"""Judge every calibration item with every enabled candidate judge (T5.4 S2).

``uv run python experiments/rq2/run_judges.py --judges experiments/rq2/configs/rq2_judges.yaml
--seed 1234 [--split test] [--sets memerag correctness] [--limit N]`` writes, per judge and split,
``<out_dir>/verdicts_<slug>_<split>.parquet`` (item id, set, metric, raw score, error, cached,
latency; no text) and ``<out_dir>/llm_calls_<slug>_<split>.parquet``. The judge cache makes a
second run free; it prints ``new LLM calls: <n>``. GPU judges run under ``pruefstand-lock``.
"""

import argparse
import asyncio
import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # run as a script: import rq2.*

from rq2.binarise import check_route, is_local
from rq2.calib_schema import CalibrationItem
from rq2.make_degraded import load_pairs
from rq2.rq2_config import (
    REPO,
    JudgeEntry,
    RQ2Config,
    SetEntry,
    load_config,
    load_items,
    set_available,
    slug,
)
from rq2.subsample import stratified_subsample

from pruefstand.core.config import JudgeConfig, LLMPolicyConfig, ModelRef
from pruefstand.core.errors import PruefstandError
from pruefstand.core.models.target import TargetInfo
from pruefstand.judges.factory import PROMPT_ROOT
from pruefstand.judges.family_guard import check_judge_families
from pruefstand.judges.judge import Judge
from pruefstand.judges.output import make_task
from pruefstand.llm.budget import Budget
from pruefstand.llm.client import LLMClient
from pruefstand.llm.factory import build_backend
from pruefstand.llm.policy import LLMPolicy
from pruefstand.llm.prompts import PromptRegistry
from pruefstand.llm.recorder import CallRecorder
from pruefstand.store.kv import DiskKVCache

CALIBRATION_NONCE = b"rq2-calibration-public-nonce"
"""Fixed, public nonce key: calibration inputs are public or local data, not attacker-written, and a
fixed key keeps the rendered prompts (and so the judge cache) reproducible across machines."""
ROW_SCHEMA = {
    "item_id": pl.String,
    "label_set": pl.String,
    "metric": pl.String,
    "judge": pl.String,
    "prompt_version": pl.String,
    "score": pl.Int64,
    "error": pl.String,
    "cached": pl.Boolean,
}


def check_families(cfg: RQ2Config, judges: list[JudgeEntry]) -> None:
    """Refuse a judge of the generator's family before any call (``check_judge_families``)."""
    info = TargetInfo(
        app_version="rq2",
        git_sha="rq2",
        image_digest=None,
        config_hash="rq2",
        corpus_version="rq2",
        models={"generator": cfg.generator},
    )
    for entry in judges:
        ref = ModelRef(id=entry.id, family=entry.family)
        check_judge_families(JudgeConfig(pr=ref, nightly=ref), [info])


def make_judge(entry: JudgeEntry, cache_dir: Path | None, recorder: CallRecorder) -> Judge:
    """Build a real judge (catalogue options, native Ollama API) with an optional disk cache."""
    policy = LLMPolicyConfig()
    backend = build_backend(ModelRef(id=entry.id, family=entry.family), policy=policy)
    cache = DiskKVCache(cache_dir, "llm") if cache_dir is not None else None
    client = LLMClient(backend, cache, Budget(None, None), recorder, LLMPolicy(policy))
    return Judge(client, entry.id, PromptRegistry([PROMPT_ROOT]), nonce_key=CALIBRATION_NONCE)


async def judge_items(
    judge: Judge,
    items: list[tuple[str, CalibrationItem]],
    concurrency: int,
    prompts: dict[str, str] | None = None,
) -> list[dict[str, object]]:
    """Score ``(set name, item)`` pairs; a failed call gives ``score=None`` and the error class."""
    gate = asyncio.Semaphore(concurrency)

    async def one(set_name: str, item: CalibrationItem) -> dict[str, object]:
        task = make_task(item.metric, **item.inputs)
        if prompts and item.metric in prompts:  # dev-only prompt work (AI13-12)
            task = task.model_copy(update={"prompt_version": prompts[item.metric]})
        row: dict[str, object] = {
            "item_id": item.item_id,
            "label_set": set_name,
            "metric": item.metric,
            "judge": judge.model,
            "prompt_version": task.prompt_version,
            "score": None,
            "error": None,
            "cached": False,
        }
        async with gate:
            try:
                verdict = await judge.score(task)
            except PruefstandError as err:
                row["error"] = type(err).__name__
                return row
        row["score"], row["cached"] = verdict.raw_score, verdict.cached
        return row

    return list(await asyncio.gather(*(one(s, i) for s, i in items)))


async def judge_pairs(
    judge: Judge, pairs: list[dict[str, object]], concurrency: int
) -> list[dict[str, object]]:
    """Score base and degraded answer of every discrimination pair (S3)."""
    gate = asyncio.Semaphore(concurrency)

    async def score(metric: str, inputs: object) -> int | None:
        async with gate:
            try:
                return (await judge.score(make_task(metric, **dict(inputs)))).raw_score  # type: ignore[call-overload]  # json object
            except PruefstandError:
                return None

    async def one(p: dict[str, object]) -> dict[str, object]:
        metric = str(p["metric"])
        base, worse = await asyncio.gather(score(metric, p["inputs"]), score(metric, p["degraded"]))
        return {
            "pair_id": p["pair_id"],
            "label_set": p["label_set"],
            "edit": p["edit"],
            "metric": metric,
            "cluster_id": p["cluster_id"],
            "judge": judge.model,
            "base": base,
            "degraded": worse,
        }

    return list(await asyncio.gather(*(one(p) for p in pairs)))


def _save_calls(calls: pl.DataFrame, path: Path) -> int:
    """Append the uncached calls of this run to the judge's call log; return their number."""
    fresh = calls.filter(~pl.col("cached"))
    if path.is_file():
        fresh = pl.concat([pl.read_parquet(path), fresh])
    if fresh.height:
        fresh.write_parquet(path)
    return calls.filter(~pl.col("cached") & pl.col("error").is_null()).height


def select_items(
    cfg: RQ2Config, entry: JudgeEntry, sets: list[SetEntry], split: str, limit: int | None
) -> list[tuple[str, CalibrationItem]]:
    """The items one judge scores: available sets, routing guard, subsample, optional limit."""
    picked: list[tuple[str, CalibrationItem]] = []
    for s in sets:
        if not set_available(s):
            sys.stdout.write(f"skip {s.name}: pending / not built\n")
            continue
        check_route(entry.id, s.name, s.path, local_only=s.local_only)
        items = load_items(s, split)  # type: ignore[arg-type]  # split is dev|test from argparse
        if entry.subsample is not None:
            items = stratified_subsample(items, entry.subsample, cfg.seed)
        picked.extend((s.name, i) for i in items[:limit])
    return picked


def run(cfg: RQ2Config, args: argparse.Namespace) -> int:
    """Run every enabled judge; return the number of new (uncached) LLM calls."""
    judges = [j for j in cfg.judges if j.enabled and (not args.judge or j.id in args.judge)]
    check_families(cfg, judges)
    sets = [cfg.set_named(n) for n in args.sets] if args.sets else list(cfg.sets)
    out_dir = REPO / cfg.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    new_calls = 0
    for entry in judges:
        items = select_items(cfg, entry, sets, args.split, args.limit)
        recorder = CallRecorder()
        judge = make_judge(entry, REPO / cfg.cache_dir, recorder)
        prompts = dict(p.split("=", 1) for p in args.prompt or [])
        if prompts and args.split != "dev":
            sys.stderr.write("--prompt is for dev-split prompt work only (AI13-12)\n")
            return new_calls
        rows = asyncio.run(judge_items(judge, items, cfg.concurrency, prompts))
        frame = pl.DataFrame(rows, schema=ROW_SCHEMA)
        suffix = "".join(f"_{m}-{v}" for m, v in sorted(prompts.items()))
        name = f"{slug(entry.id)}_{args.split}{suffix}"
        frame.write_parquet(out_dir / f"verdicts_{name}.parquet")
        pairs = load_pairs() if args.pairs else []
        if pairs:
            scored = asyncio.run(judge_pairs(judge, pairs, cfg.concurrency))
            pl.DataFrame(scored, infer_schema_length=None).write_parquet(
                out_dir / f"pairs_{slug(entry.id)}.parquet"
            )
        fresh = _save_calls(recorder.to_frame(), out_dir / f"llm_calls_{name}.parquet")
        new_calls += fresh
        errors = frame.filter(pl.col("error").is_not_null()).height
        local = "local" if is_local(entry.id) else "hosted"
        sys.stdout.write(
            f"{entry.id} ({local}): {frame.height} items, {errors} errors, {fresh} new calls\n"
        )
    sys.stdout.write(f"new LLM calls: {new_calls}\n")
    return new_calls


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--judges", type=Path, default=REPO / "experiments/rq2/configs/rq2_judges.yaml"
    )
    parser.add_argument("--seed", type=int, default=1234)
    parser.add_argument("--split", choices=["dev", "test"], default="test")
    parser.add_argument("--sets", nargs="*", default=None)
    parser.add_argument("--judge", nargs="*", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--prompt", nargs="*", help="dev only: metric=version overrides")
    parser.add_argument("--pairs", action="store_true", help="also score the degraded pairs (S3)")
    args = parser.parse_args(argv)
    cfg = load_config(args.judges)
    if args.seed != cfg.seed:
        sys.stderr.write(f"--seed {args.seed} differs from the config seed {cfg.seed}\n")
        return 2
    run(cfg, args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
