"""Generate QA candidates from PUBLIC corpus chunks with the GitHub Models datagen model (T4.2).

Pass 1 (network, no GPU; resumable, quota-aware)::

    uv run python scripts/generate_qa.py --pass generate --tenant kanzlei_mueller --n 30 \
        --model github/openai/gpt-4.1-mini --cross-check 0.1 --seed 7

Pass 2 (day mode on the VM, local judge model, no datagen call)::

    pruefstand-lock uv run python scripts/generate_qa.py --pass validate --tenant kanzlei_mueller \
        --n 30 --seed 7

The credential is ``PRUEFSTAND_GH_MODELS_TOKEN`` (Models: read, D333); it is never printed. Output
goes to ``datasets/_work/<run>/`` (git-ignored): ``candidates.jsonl``, ``cross_check.jsonl``,
``ledger.jsonl`` (the resume record), ``validation.jsonl``, ``summary.json``. Only public text is
sampled (attack and private chunks are skipped); chunks of the in-domain dev set are excluded.
``--max-requests`` caps the requests of one client; a daily quota (HTTP 429) or the cap stops the
batch cleanly, partial output is written and the next call continues where it stopped.

Exit codes: 0 complete, 1 failure, 2 refused (arguments, model, credential, lock), 3 stopped by a
quota or the request cap (run again later).
"""

import argparse
import asyncio
import hashlib
import json
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from generate_qa_args import DEFAULT_CATALOGUE, build_parser
from generate_qa_clients import ClientFactory, JudgeFactory, default_client, default_judge
from generate_qa_ledger import (
    CANDIDATES,
    CROSS_CHECK,
    SUMMARY,
    VALIDATION,
    append_entry,
    dump_line,
    planned_candidates,
    read_candidates,
    read_ledger,
    write_lines,
)
from private_doc_plan import default_model

from pruefstand.core.config import ModelRef
from pruefstand.core.errors import ConfigError, PruefstandError
from pruefstand.core.models.corpus import Chunk
from pruefstand.core.models.dataset import QACandidate
from pruefstand.dataset.cross_check import (
    CrossCheckPlan,
    CrossCheckRow,
    check_second_model,
    cross_check,
    pick_sample,
    row_key,
)
from pruefstand.dataset.datagen_guard import check_datagen_model
from pruefstand.dataset.datagen_pins import PROMPT_VERSIONS
from pruefstand.dataset.generate import GenStats, run_units
from pruefstand.dataset.generate_units import build_units, parse_prompt_version
from pruefstand.dataset.generate_validate import validate_candidates
from pruefstand.dataset.sampling import (
    load_chunks,
    load_excluded_doc_ids,
    sample_chunks,
    sample_cross_lingual_pairs,
    sample_multi_hop_pairs,
)
from pruefstand.ingest.citation_graph import load_citation_graph
from pruefstand.llm.families import family_of
from pruefstand.llm.recorder import CallRecorder

EXIT_STOPPED = 3
_STOP_COUNTERS = ("quota_exhausted", "budget_exceeded", "llm_error")


def _plan(args: argparse.Namespace, chunks: list[Chunk]) -> list[Sequence[Chunk]]:
    """The seeded plan: one chunk or one pair per unit, tenants in sorted order."""
    if not args.exclude_file.is_file():
        msg = f"--exclude-file {args.exclude_file.name} is not a file (exclusion list)"
        raise ConfigError(msg)
    exclude = load_excluded_doc_ids(args.exclude_file)
    rng = np.random.default_rng([args.seed, 0])
    tenants = sorted({c.tenant for c in chunks}) if args.tenant == "all" else [args.tenant]
    graph: dict[str, tuple[str, ...]] | None = None
    if args.citation_graph is not None:
        graph = {str(k): v for k, v in load_citation_graph(args.citation_graph).items()}
    plan: list[Sequence[Chunk]] = []
    for tenant in tenants:
        pool = [c for c in chunks if c.tenant == tenant]
        if args.category == "multi_hop":
            plan += sample_multi_hop_pairs(pool, args.n, rng, graph=graph, exclude_doc_ids=exclude)
        elif args.category == "cross_lingual":
            plan += sample_cross_lingual_pairs(pool, args.n, rng, exclude_doc_ids=exclude)
        else:
            plan += [(c,) for c in sample_chunks(pool, args.n, rng, exclude_doc_ids=exclude)]
    return plan


def _run_dir(args: argparse.Namespace) -> Path:
    name = args.run or f"{args.tenant}-{args.category}-s{args.seed}-n{args.n}"
    if not name or "/" in name or name.startswith("."):
        msg = f"unsafe run name {name!r}"
        raise ConfigError(msg)
    return Path(args.work_dir) / name


@dataclass
class Job:
    """What the passes share: arguments, run directory, corpus, client factory and counters."""

    args: argparse.Namespace
    run_dir: Path
    chunks: list[Chunk]
    make: ClientFactory
    stats: GenStats
    recorder: CallRecorder


async def _generate(job: Job) -> list[QACandidate]:
    """Send the units the ledger does not hold yet; write ``candidates.jsonl`` of the plan."""
    args, run_dir, chunks, stats = job.args, job.run_dir, job.chunks, job.stats
    spec = parse_prompt_version(PROMPT_VERSIONS[args.category])
    units = build_units(
        spec, args.model, _plan(args, chunks), np.random.default_rng([args.seed, 1])
    )
    ledger = read_ledger(run_dir)
    if any(u.key not in ledger for u in units):
        ref = ModelRef(id=args.model, family=family_of(args.model))
        client = job.make(ref, args.max_requests, job.recorder)
        await run_units(
            spec,
            units,
            client,
            args.model,
            stats,
            concurrency=args.concurrency,
            sink=lambda key, cand: append_entry(run_dir, key, cand),
            skip=set(ledger),
        )
    entries = read_ledger(run_dir)
    keys = [u.key for u in units]
    stats.add(
        "invalid_total", sum(1 for k in keys if k in entries and entries[k].candidate is None)
    )
    cands = planned_candidates(entries, keys)
    write_lines(run_dir / CANDIDATES, [dump_line(c) for c in cands])
    return cands


def _read_rows(path: Path) -> dict[str, CrossCheckRow]:
    if not path.is_file():
        return {}
    rows = [CrossCheckRow.model_validate_json(x) for x in path.read_text("utf-8").splitlines() if x]
    return {row_key(r.primary): r for r in rows if r.second is not None}


async def _cross(job: Job, cands: list[QACandidate]) -> None:
    """Cross-check a seeded sample; rows of an earlier run are reused (no request)."""
    args, run_dir, stats = job.args, job.run_dir, job.stats
    done = _read_rows(run_dir / CROSS_CHECK)
    picked = pick_sample(len(cands), args.cross_check, np.random.default_rng([args.seed, 2]))
    if picked and all(row_key(cands[i]) in done for i in picked):
        rows = [done[row_key(cands[i])] for i in picked]
        stats.add("cross_checked", len(rows))
    else:
        second = ModelRef(id=args.cross_check_model, family=family_of(args.cross_check_model))
        plan = CrossCheckPlan(
            model=args.cross_check_model, primary_model=args.model, fraction=args.cross_check
        )
        rows = await cross_check(
            cands,
            {c.chunk_id: c for c in job.chunks},
            job.make(second, args.max_requests, job.recorder),
            plan,
            np.random.default_rng([args.seed, 2]),
            stats=stats,
            done=done,
        )
    write_lines(run_dir / CROSS_CHECK, [dump_line(r) for r in rows])


async def _validate(
    args: argparse.Namespace, run_dir: Path, chunks: list[Chunk], make_judge: JudgeFactory
) -> tuple[int, int]:
    """Pass 2: re-check the cached candidates; returns ``(validated, with_problems)``."""
    cands = read_candidates(run_dir)
    if not cands:
        msg = f"{run_dir.name}: no candidates.jsonl; run --pass generate first"
        raise ConfigError(msg)
    judge, model = None, None
    if not args.no_judge:
        if os.environ.get("PRUEFSTAND_LOCK_HELD") != "1":
            msg = (
                "pass 2 with the local judge runs under 'pruefstand-lock' (D212); or use --no-judge"
            )
            raise ConfigError(msg)
        ref = (
            ModelRef(id=args.judge_model, family=family_of(args.judge_model))
            if args.judge_model
            else default_model(DEFAULT_CATALOGUE)
        )
        judge, model = make_judge(ref), ref.id
    rows = await validate_candidates(cands, {c.chunk_id: c for c in chunks}, judge, model)
    write_lines(run_dir / VALIDATION, [dump_line(r) for r in rows])
    return len(rows), sum(1 for r in rows if r.problems)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""


def _report(stats: GenStats, recorder: CallRecorder, cands: int, run_dir: Path) -> str:
    counts = stats.counts
    cost = sum(float(str(r["cost_usd"] or 0)) for r in recorder.rows)
    line = (
        f"candidates={cands} invalid={counts['invalid_total']} cost_usd={cost:.2f} "
        f"cross_checked={counts['cross_checked']} skipped_private={counts['skipped_private']}"
    )
    detail = {k: v for k, v in sorted(counts.items()) if k not in {"invalid_total"} and v}
    summary = {"line": line, "counts": detail, "candidates_sha256": _sha(run_dir / CANDIDATES)}
    (run_dir / SUMMARY).write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n", "utf-8")
    return line + (f"\ndetail: {json.dumps(detail, sort_keys=True)}" if detail else "")


async def _run(args: argparse.Namespace, make: ClientFactory, make_judge: JudgeFactory) -> int:
    check_datagen_model(args.model)
    if args.cross_check > 0:
        check_second_model(args.cross_check_model, args.model)
    if args.max_requests is not None:
        args.concurrency = 1  # the cap is exact only when requests are sent one at a time
    job = Job(args, _run_dir(args), load_chunks(args.corpus_dir), make, GenStats(), CallRecorder())
    stopped = False
    if args.phase in {"generate", "both"}:
        cands = await _generate(job)
        stopped = any(job.stats.counts[k] for k in _STOP_COUNTERS)
        if args.cross_check > 0 and not stopped and cands:
            await _cross(job, cands)
            stopped = any(job.stats.counts[k] for k in _STOP_COUNTERS)
        print(_report(job.stats, job.recorder, len(cands), job.run_dir))
    if args.phase in {"validate", "both"} and not stopped:
        validated, problems = await _validate(args, job.run_dir, job.chunks, make_judge)
        print(f"validated={validated} with_problems={problems} datagen_calls=0")
    if stopped:
        print("stopped by a quota or the request cap; run the same command again to continue")
    return EXIT_STOPPED if stopped else 0


def main(
    argv: Sequence[str] | None = None,
    *,
    client: ClientFactory = default_client,
    judge: JudgeFactory = default_judge,
) -> int:
    """Run the script; returns the exit code (see the module docstring)."""
    args = build_parser((__doc__ or "").split("\n\n")[0]).parse_args(argv)
    try:
        return asyncio.run(_run(args, client, judge))
    except ConfigError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    except PruefstandError as exc:
        print(f"failed: {type(exc).__name__}: {str(exc)[:200]}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
