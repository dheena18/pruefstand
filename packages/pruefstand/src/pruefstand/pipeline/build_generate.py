"""Stage ``generate`` of ``build_dataset``: QA candidates from corpus chunks (T4.7a, T4.2).

The datagen model is a GitHub Models free-tier model (public text only). Finished units are kept in
``generate_ledger.jsonl`` as they arrive, so a run stopped by the daily quota continues where it
stopped. ``generation.candidates_from`` skips the model calls and takes the candidates of an earlier
``scripts/generate_qa.py`` run.
"""

from collections.abc import Mapping, Sequence
from pathlib import Path

import numpy as np
from pydantic import BaseModel, ConfigDict, ValidationError

from pruefstand.core.config import ModelRef
from pruefstand.core.errors import ConfigError, DatasetError
from pruefstand.core.models.corpus import Chunk
from pruefstand.core.models.dataset import QACandidate
from pruefstand.dataset.datagen_guard import check_datagen_model
from pruefstand.dataset.datagen_pins import PROMPT_VERSIONS
from pruefstand.dataset.generate import GenStats, run_units
from pruefstand.dataset.generate_units import PromptSpec, Unit, build_units, parse_prompt_version
from pruefstand.dataset.sampling import (
    load_chunks,
    load_excluded_doc_ids,
    sample_chunks,
    sample_cross_lingual_pairs,
    sample_multi_hop_pairs,
)
from pruefstand.ingest.citation_graph import load_citation_graph
from pruefstand.llm.client import LLMClient
from pruefstand.llm.recorder import CallRecorder
from pruefstand.pipeline.build_context import BuildContext, StageResult

LEDGER = "generate_ledger.jsonl"


class LedgerEntry(BaseModel):
    """One finished unit: its key and the candidate (None = the answer stayed invalid)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    candidate: QACandidate | None


def _plan(
    ctx: BuildContext, spec: PromptSpec, chunks: Sequence[Chunk], n: int, rng: np.random.Generator
) -> list[Sequence[Chunk]]:
    gen = ctx.cfg.generation
    exclude = load_excluded_doc_ids(gen.exclude_file) if gen.exclude_file else frozenset()
    graph = None
    if gen.citation_graph is not None:
        graph = {str(k): v for k, v in load_citation_graph(gen.citation_graph).items()}
    plan: list[Sequence[Chunk]] = []
    for tenant in sorted({c.tenant for c in chunks}):
        pool = [c for c in chunks if c.tenant == tenant]
        if spec.category.value == "multi_hop":
            plan += sample_multi_hop_pairs(pool, n, rng, graph=graph, exclude_doc_ids=exclude)
        elif spec.category.value == "cross_lingual":
            plan += sample_cross_lingual_pairs(pool, n, rng, exclude_doc_ids=exclude)
        else:
            plan += [(c,) for c in sample_chunks(pool, n, rng, exclude_doc_ids=exclude)]
    return plan


def _read_ledger(path: Path) -> dict[str, LedgerEntry]:
    """Read the ledger; only a truncated last line (an interrupted write) is skipped."""
    if not path.is_file():
        return {}
    lines = path.read_text("utf-8").splitlines()
    entries: dict[str, LedgerEntry] = {}
    for number, line in enumerate(lines, start=1):
        try:
            entry = LedgerEntry.model_validate_json(line)
        except ValidationError as exc:
            if number == len(lines):
                continue
            msg = f"{path.name}:{number}: not a valid ledger entry"
            raise DatasetError(msg) from exc
        entries[entry.key] = entry
    return entries


def _finished(units: Sequence[Unit], done: Mapping[str, LedgerEntry]) -> list[QACandidate]:
    found = (done[u.key].candidate for u in units if u.key in done)
    return [c for c in found if c is not None]


def specs_of(ctx: BuildContext) -> list[tuple[int, PromptSpec, int]]:
    """Return ``(index, prompt spec, units per tenant)`` for the configured categories.

    Raises:
        ConfigError: An unknown category, or ``--only`` names no configured prompt.
    """
    gen = ctx.cfg.generation
    found: list[tuple[int, PromptSpec, int]] = []
    for index, category in enumerate(sorted(gen.units)):
        if category not in PROMPT_VERSIONS:
            msg = (
                f"generation.units: unknown category {category!r}; known: {sorted(PROMPT_VERSIONS)}"
            )
            raise ConfigError(msg)
        spec = parse_prompt_version(gen.prompt_versions.get(category, PROMPT_VERSIONS[category]))
        found.append((index, spec, gen.units[category]))
    if ctx.only is not None:
        found = [f for f in found if ctx.only in {f[1].prompt_id, f[1].name}]
        if not found:
            msg = f"--only {ctx.only!r} names no configured prompt"
            raise ConfigError(msg)
    return found


def _copied(source: Path) -> list[QACandidate]:
    if not source.is_file():
        msg = f"generation.candidates_from {source.name} is not a file"
        raise ConfigError(msg)
    try:
        return [
            QACandidate.model_validate_json(x) for x in source.read_text("utf-8").splitlines() if x
        ]
    except ValidationError as exc:
        msg = f"{source.name}: not a valid candidates.jsonl ({exc.error_count()} problems)"
        raise DatasetError(msg) from exc


async def generate_stage(ctx: BuildContext) -> StageResult:
    """Run the ``generate`` stage; return the candidates and the counters.

    Raises:
        ConfigError: No datagen model, a datagen model that breaks the family rule, or no units.
        DatasetError: ``candidates_from`` is unreadable, or a quota stopped the run (run again).
    """
    gen = ctx.cfg.generation
    if gen.candidates_from is not None:
        rows = _copied(gen.candidates_from)
        return list(rows), {"candidates": len(rows), "copied": 1}
    models = ctx.cfg.models
    if models is None:
        msg = "the generate stage needs models.datagen (or generation.candidates_from)"
        raise ConfigError(msg)
    check_datagen_model(models.datagen)
    chunks = load_chunks(ctx.cfg.corpus_dir)
    stats, recorder = GenStats(), CallRecorder()
    ledger_path = ctx.work.root / LEDGER
    ctx.work.root.mkdir(parents=True, exist_ok=True)
    wanted: list[QACandidate] = []
    for index, spec, n in specs_of(ctx):
        rng_plan = np.random.default_rng([ctx.cfg.seed, 0, index])
        units = build_units(
            spec, models.datagen.id, _plan(ctx, spec, chunks, n, rng_plan),
            np.random.default_rng([ctx.cfg.seed, 1, index]),
        )  # fmt: skip
        done = _read_ledger(ledger_path)
        if any(u.key not in done for u in units):
            client = ctx.clients.datagen(models.datagen, gen.max_requests, recorder)
            await _send(
                ctx,
                spec,
                units,
                client,
                ref=models.datagen,
                stats=stats,
                done=done,
                ledger=ledger_path,
            )
            done = _read_ledger(ledger_path)
        wanted += _finished(units, done)
        missing = sum(1 for u in units if u.key not in done)
        if missing:
            msg = f"{spec.name}: {missing} units not finished (quota or cap); run the stage again"
            raise DatasetError(msg)
    return list(_merged(ctx, wanted)), dict(stats.counts)


async def _send(
    ctx: BuildContext,
    spec: PromptSpec,
    units: Sequence[Unit],
    client: LLMClient,
    *,
    ref: ModelRef,
    stats: GenStats,
    done: Mapping[str, LedgerEntry],
    ledger: Path,
) -> None:
    def sink(key: str, cand: QACandidate | None) -> None:
        with ledger.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(LedgerEntry(key=key, candidate=cand).model_dump_json() + "\n")

    await run_units(
        spec, units, client, ref.id, stats,
        concurrency=ctx.cfg.generation.concurrency, sink=sink, skip=set(done),
    )  # fmt: skip


def _merged(ctx: BuildContext, fresh: list[QACandidate]) -> list[QACandidate]:
    """With ``--only`` keep the earlier candidates of the prompts that were not regenerated."""
    if ctx.only is None:
        return fresh
    replaced = {spec.prompt_id for _, spec, _ in specs_of(ctx)}
    before = ctx.work.read("generate", QACandidate) if ctx.work.path("generate").is_file() else []
    kept = [c for c in before if parse_prompt_version(c.prompt_version).prompt_id not in replaced]
    return kept + fresh
