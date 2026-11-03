"""QA generation with the datagen model (T4.2, interfaces §14).

``generate_qa`` (one chunk per question) and ``generate_qa_pairs`` (two chunks) ask the pinned
GitHub Models datagen model for a German user question, a reference answer, the citation and the
verbatim evidence, and return ``QACandidate`` objects. Only public text is sent (ADR-0019, D330).
Runs are resumable: every answer is cached by the ``LLMClient``, a finished unit can be reported
to a ``sink`` and skipped on the next run, and an exhausted request budget or a provider quota
(``BudgetExceeded``, ``QuotaExhausted``) stops the batch cleanly with the candidates so far.
"""

import asyncio
from collections import Counter
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass, field

import numpy as np

from pruefstand.core.errors import (
    BudgetExceeded,
    ConfigError,
    LLMError,
    PolicyViolation,
    QuotaExhausted,
)
from pruefstand.core.logging import get_logger
from pruefstand.core.models.corpus import Chunk
from pruefstand.core.models.dataset import QACandidate
from pruefstand.core.models.llm import LLMRequest
from pruefstand.dataset.datagen_guard import check_datagen_model
from pruefstand.dataset.generate_units import (
    PROMPT_ROOT,
    PromptSpec,
    QAAnswer,
    Unit,
    build_request,
    build_units,
    make_candidate,
    parse_prompt_version,
)
from pruefstand.dataset.sampling import is_public_text
from pruefstand.dataset.to_case import license_config_of
from pruefstand.llm.client import LLMClient
from pruefstand.llm.prompts import PromptRegistry

DEFAULT_CONCURRENCY = 4
INVALID_JSON = "invalid JSON after one repair"
Sink = Callable[[str, QACandidate | None], None]
_log = get_logger(__name__)


@dataclass
class GenStats:
    """Counters of a generation run.

    ``counts`` keys: candidates, invalid, evidence_invalid, citation_unparsed, skipped_private,
    license_mixed, llm_error, budget_exceeded, quota_exhausted, cross_checked.
    """

    counts: Counter[str] = field(default_factory=Counter)

    def add(self, key: str, n: int = 1) -> None:
        """Increase counter ``key`` by ``n``."""
        self.counts[key] += n


def registry() -> PromptRegistry:
    """The prompt registry of the dataset package (``dataset/prompts``)."""
    return PromptRegistry([PROMPT_ROOT])


async def run_units(
    spec: PromptSpec,
    units: Sequence[Unit],
    llm: LLMClient,
    model: str,
    stats: GenStats,
    *,
    concurrency: int = DEFAULT_CONCURRENCY,
    sink: Sink | None = None,
    skip: Collection[str] = frozenset(),
) -> list[QACandidate | None]:
    """Send the units (at most ``concurrency`` at a time); return one result per unit, in order.

    A unit is ``None`` when it was skipped, refused, invalid or not run because the batch stopped.
    ``sink(key, candidate)`` is called for each finished unit (candidate, or None for an answer
    that stayed invalid after the repair); units that stopped early are not reported, so the next
    run sends them again.
    """
    prompts = registry()
    gate = asyncio.Semaphore(max(1, concurrency))
    stop = asyncio.Event()

    async def one(unit: Unit) -> QACandidate | None:
        if unit.key in skip or not _sendable(unit, stats):
            return None
        async with gate:
            if stop.is_set():
                return None
            request = build_request(spec, unit, model, prompts)
            answer = await _ask(llm, request, unit, stats, stop=stop, sink=sink)
        if answer is None:
            return None
        cand, notes = make_candidate(spec, unit, answer)
        for note in notes:
            stats.add(note)
        stats.add("candidates")
        if sink is not None:
            sink(unit.key, cand)
        return cand

    return list(await asyncio.gather(*(one(u) for u in units)))


async def _ask(
    llm: LLMClient,
    request: LLMRequest,
    unit: Unit,
    stats: GenStats,
    *,
    stop: asyncio.Event,
    sink: Sink | None,
) -> QAAnswer | None:
    """Send one request; a refusal, a stop or a failure is counted and gives None."""
    try:
        return await llm.complete_json(request, QAAnswer)
    except QuotaExhausted:
        _stop(stop, stats, "quota_exhausted", request.model)
    except BudgetExceeded:
        _stop(stop, stats, "budget_exceeded", request.model)
    except PolicyViolation:
        stats.add("skipped_private")
    except LLMError as exc:
        _failed(exc, unit, stats, sink)
    return None


def _sendable(unit: Unit, stats: GenStats) -> bool:
    if not all(is_public_text(c) for c in unit.chunks):
        stats.add("skipped_private")
        return False
    if len(unit.chunks) > 1 and license_config_of(unit.chunks) is None:
        stats.add("license_mixed")
        return False
    return True


def _stop(stop: asyncio.Event, stats: GenStats, reason: str, model: str) -> None:
    if not stop.is_set():
        _log.warning(reason, model=model)
    stop.set()
    stats.add(reason)


def _failed(exc: LLMError, unit: Unit, stats: GenStats, sink: Sink | None) -> None:
    if str(exc).startswith(INVALID_JSON):
        stats.add("invalid")
        if sink is not None:
            sink(unit.key, None)
    else:  # an outage is not a verdict on the unit: it stays open for the next run
        stats.add("llm_error")
        _log.warning("datagen_call_failed", error=type(exc).__name__, status=exc.status)


async def generate_qa(  # noqa: PLR0913  (interfaces §14 signature plus keyword options)
    chunks: Sequence[Chunk],
    llm: LLMClient,
    model: str,
    prompt_version: str,
    rng: np.random.Generator,
    *,
    concurrency: int = DEFAULT_CONCURRENCY,
    stats: GenStats | None = None,
    sink: Sink | None = None,
    skip: Collection[str] = frozenset(),
) -> list[QACandidate]:
    """Generate one candidate per chunk with a single-chunk prompt (factual, comparison).

    Args:
        chunks: Source chunks; non-public chunks are skipped and counted ``skipped_private``.
        llm: Client built with ``datagen_policy`` (GitHub Models, public-text datagen).
        model: ``github/<model>`` of a family other than ``qwen`` and ``gemma``.
        prompt_version: ``qa_factual_de_v1`` or ``qa_comparison_de_v1``.
        rng: Seeded generator; draws the request seed and the style of every chunk in order.
        concurrency: Requests in flight.
        stats: Receives the counters.
        sink: Called with ``(unit key, candidate or None)`` for each finished chunk.
        skip: Unit keys finished in an earlier run; they are not sent but keep their draws.

    Returns:
        The candidates in input order. The list is shorter when answers stayed invalid or a
        quota or budget stopped the batch.

    Raises:
        ConfigError: The model or the prompt is not allowed for this function.
    """
    spec = parse_prompt_version(prompt_version)
    if spec.is_pair:
        msg = f"{prompt_version} is a pair prompt; generate_qa takes single-chunk prompts"
        raise ConfigError(msg)
    groups = [(c,) for c in chunks]
    options = _Options(concurrency, stats, sink, skip)
    return await _generate(spec, groups, llm, model, rng, options=options)


async def generate_qa_pairs(  # noqa: PLR0913  (interfaces §14 signature plus keyword options)
    pairs: Sequence[tuple[Chunk, Chunk]],
    llm: LLMClient,
    model: str,
    prompt_version: str,
    rng: np.random.Generator,
    *,
    concurrency: int = DEFAULT_CONCURRENCY,
    stats: GenStats | None = None,
    sink: Sink | None = None,
    skip: Collection[str] = frozenset(),
) -> list[QACandidate]:
    """Generate one candidate per chunk pair (multi-hop, cross-lingual).

    Same arguments as ``generate_qa``, with ``prompt_version`` ``qa_multi_hop_de_v1`` or
    ``qa_cross_lingual_de_v1``. A pair that would mix two share-alike licences is dropped before
    any request (``license_mixed``). The candidate holds both chunk ids (``chunk_id`` = the gold
    chunk, ``extra_chunk_ids`` = the other).

    Raises:
        ConfigError: The model or the prompt is not allowed for this function.
    """
    spec = parse_prompt_version(prompt_version)
    if not spec.is_pair:
        msg = f"{prompt_version} is a single-chunk prompt; generate_qa_pairs needs a pair prompt"
        raise ConfigError(msg)
    options = _Options(concurrency, stats, sink, skip)
    return await _generate(spec, list(pairs), llm, model, rng, options=options)


@dataclass(frozen=True)
class _Options:
    concurrency: int
    stats: GenStats | None
    sink: Sink | None
    skip: Collection[str]


async def _generate(
    spec: PromptSpec,
    groups: Sequence[Sequence[Chunk]],
    llm: LLMClient,
    model: str,
    rng: np.random.Generator,
    *,
    options: _Options,
) -> list[QACandidate]:
    check_datagen_model(model)
    counts = options.stats if options.stats is not None else GenStats()
    units = build_units(spec, model, groups, rng)
    results = await run_units(
        spec, units, llm, model, counts,
        concurrency=options.concurrency, sink=options.sink, skip=options.skip,
    )  # fmt: skip
    return [r for r in results if r is not None]
