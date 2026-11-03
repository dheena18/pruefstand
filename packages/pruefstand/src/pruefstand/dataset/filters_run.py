"""Orchestration of the QA filters (T4.3): ``filter_candidates``.

The deterministic checks run first (chunks present, citation and evidence, copy rules, cluster
overlap of pairs), then the support check, then the embedding near-duplicate filter. Every dropped
candidate is returned with its reasons and counted in the report; nothing is dropped silently, and
a candidate the support model could not judge because a quota stopped the batch is reported as
``not_checked``, never as kept.
"""

import asyncio
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict

from pruefstand.core.errors import BudgetExceeded, QuotaExhausted
from pruefstand.core.ids import ChunkId
from pruefstand.core.models.corpus import Chunk
from pruefstand.core.models.dataset import FilterConfig, FilterResult, QACandidate
from pruefstand.dataset.filters import Embedder, check_support, check_support_family, dedupe_report
from pruefstand.dataset.filters_checks import (
    StyleReport,
    check_evidence,
    drop_cluster_overlap,
    sources_of,
    style_report,
)
from pruefstand.dataset.filters_text import check_overlap
from pruefstand.dataset.to_case import case_id_of
from pruefstand.llm.client import LLMClient


class Dropped(BaseModel):
    """A candidate that did not pass, with the reasons (``FILTER_REASONS``)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate: QACandidate
    reasons: tuple[str, ...]


class FilterReport(BaseModel):
    """Counts of one filter run (``filter_report.json``).

    ``reasons`` counts candidates per reason (a candidate with two reasons is in both counts);
    ``not_checked`` candidates were never judged because a quota or cap stopped the support check.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    total: int
    kept: int
    dropped: int
    not_checked: int
    reasons: dict[str, int]
    support: Literal["checked", "skipped"]
    support_model: str | None
    style: StyleReport
    config: FilterConfig


@dataclass(frozen=True)
class SupportSetup:
    """The support model: its client, its id and the generator model it must differ from."""

    llm: LLMClient
    model: str
    generator_model: str


@dataclass(frozen=True)
class FilterOutcome:
    """Result of ``filter_candidates``: kept (input order), dropped rows and the report."""

    kept: list[QACandidate]
    dropped: list[Dropped]
    report: FilterReport


def _static_reasons(
    c: QACandidate, chunks: Mapping[ChunkId, Chunk], config: FilterConfig
) -> list[str]:
    sources = sources_of(c, chunks)
    if sources is None:
        return ["chunk_missing"]
    reasons = list(check_evidence(c, sources).reasons)
    for source in sources:
        verdict = check_overlap(
            c, source, config.max_ngram_overlap, long_copy_words=config.long_copy_words
        )
        reasons += [r for r in verdict.reasons if r not in reasons]
    return reasons


async def _support_stage(
    cands: Sequence[QACandidate],
    chunks: Mapping[ChunkId, Chunk],
    setup: SupportSetup,
    concurrency: int,
) -> dict[str, FilterResult | None]:
    """Run the support check; a candidate that was not judged (quota, cap) maps to None."""
    gate = asyncio.Semaphore(max(1, concurrency))
    stop = asyncio.Event()

    async def one(c: QACandidate) -> FilterResult | None:
        async with gate:
            if stop.is_set():
                return None
            try:
                return await check_support(
                    c,
                    chunks[c.chunk_id],
                    setup.llm,
                    setup.model,
                    extra=[chunks[i] for i in c.extra_chunk_ids],
                )
            except (QuotaExhausted, BudgetExceeded):
                stop.set()
                return None

    results = await asyncio.gather(*(one(c) for c in cands))
    return {case_id_of(c): r for c, r in zip(cands, results, strict=True)}


def _split_verdicts(
    live: Sequence[QACandidate],
    verdicts: Mapping[str, FilterResult | None],
    dropped: list[Dropped],
) -> tuple[list[QACandidate], int]:
    """Keep the supported candidates, add the rejected to ``dropped``, count the unjudged."""
    checked: list[QACandidate] = []
    not_checked = 0
    for c in live:
        verdict = verdicts[case_id_of(c)]
        if verdict is None:
            not_checked += 1
        elif verdict.kept:
            checked.append(c)
        else:
            dropped.append(Dropped(candidate=c, reasons=verdict.reasons))
    return checked, not_checked


async def filter_candidates(
    cands: Sequence[QACandidate],
    chunks: Mapping[ChunkId, Chunk],
    embed: Embedder,
    config: FilterConfig = FilterConfig(),  # noqa: B008  (a frozen model)
    *,
    support: SupportSetup | None = None,
) -> FilterOutcome:
    """Run all filters; return the kept candidates, the dropped ones and the counts.

    Order: chunks present, citation and evidence, copy rules (``check_overlap``), cluster overlap
    of pairs, support check (``support`` None skips it and the report says so), near-duplicates.
    A candidate is dropped at the first stage that rejects it; all reasons of that stage are
    recorded.

    Args:
        cands: Candidates of ``candidates.jsonl``.
        chunks: Their source chunks by id.
        embed: Question embedding function for the near-duplicate stage.
        config: Thresholds.
        support: The support model, or None to skip the support stage.

    Raises:
        ConfigError: The support model has the generator's family.
    """
    if support is not None:
        check_support_family(support.model, support.generator_model)
    dropped: list[Dropped] = []
    live: list[QACandidate] = []
    for c in cands:
        reasons = _static_reasons(c, chunks, config)
        if reasons:
            dropped.append(Dropped(candidate=c, reasons=tuple(reasons)))
        else:
            live.append(c)
    live, overlap = drop_cluster_overlap(live, chunks)
    dropped += [Dropped(candidate=c, reasons=("cluster_overlap",)) for c in overlap]
    not_checked = 0
    if support is not None:
        verdicts = await _support_stage(live, chunks, support, config.concurrency)
        live, not_checked = _split_verdicts(live, verdicts, dropped)
    kept, duplicates = dedupe_report(live, embed, config.max_sim)
    dropped += [Dropped(candidate=c, reasons=("near_duplicate",)) for c in duplicates]
    keep = {id(c) for c in kept}
    ordered = [c for c in live if id(c) in keep]
    return FilterOutcome(
        ordered,
        dropped,
        _report(cands, ordered, dropped, not_checked=not_checked, support=support, config=config),
    )


def _report(
    cands: Sequence[QACandidate],
    kept: Sequence[QACandidate],
    dropped: Sequence[Dropped],
    *,
    not_checked: int,
    support: SupportSetup | None,
    config: FilterConfig,
) -> FilterReport:
    reasons = Counter(r for d in dropped for r in d.reasons)
    return FilterReport(
        total=len(cands),
        kept=len(kept),
        dropped=len(dropped),
        not_checked=not_checked,
        reasons=dict(sorted(reasons.items())),
        support="checked" if support is not None else "skipped",
        support_model=support.model if support is not None else None,
        style=style_report(kept, config.min_laie_share, config.style_min_n),
        config=config,
    )
