"""Seeded sampling of chunks and chunk pairs for QA generation (T4.2 S2).

Only public law, decision and EUR-Lex text is sampled: attack chunks and every chunk whose source
is not on the public list (synthetic private documents) are skipped (ADR-0019, D330). Chunks of
the in-domain development set (``indomain_dev_sources.json``, D581, D602) are excluded by
document id. All draws use the generator the caller passes.
"""

import json
import re
from collections.abc import Collection, Mapping, Sequence
from itertools import pairwise
from pathlib import Path

import numpy as np
from pydantic import ValidationError

from pruefstand.core.citations import parse_one
from pruefstand.core.enums import Lang
from pruefstand.core.errors import DatasetError
from pruefstand.core.models.corpus import Chunk
from pruefstand.dataset.to_case import license_config_of
from pruefstand.ingest.corpus_files import FILE_SUFFIX, iter_lines

PUBLIC_SOURCE_PREFIXES = ("gii", "eurlex", "oldp", "germanquad", "germanrag")
MIN_TOKENS = 40
MAX_EXCLUSION_BYTES = 4 * 1024 * 1024
_TOKEN = re.compile(r"\w+|[^\w\s]")
_LEADING_NUMBER = re.compile(r"\d+")

ChunkPair = tuple[Chunk, Chunk]


def estimate_tokens(text: str) -> int:
    """Count words and punctuation marks (the unit of the 40-token minimum).

    Examples:
        >>> estimate_tokens("Ein Monat, bitte.")
        5
    """
    return len(_TOKEN.findall(text))


def is_public_text(chunk: Chunk) -> bool:
    """Return True for public law, decision and EUR-Lex text that may go to GitHub Models.

    Examples:
        >>> from pruefstand.core.models.corpus import Chunk
        >>> kw = dict(doc_id="d", tenant="t", lang="de", text="x", citation_key=None, section=None,
        ...           parallel_id=None, version_date=None, license="l")
        >>> is_public_text(Chunk(chunk_id="a", source="gii:bgb", **kw))
        True
        >>> is_public_text(Chunk(chunk_id="a", source="synthetic:handwritten", **kw))
        False
    """
    return not chunk.is_attack and chunk.source.split(":", 1)[0] in PUBLIC_SOURCE_PREFIXES


def load_chunks(corpus_dir: Path) -> list[Chunk]:
    """Read every ``*.chunks.jsonl`` of a corpus version, sorted by ``chunk_id``.

    Raises:
        DatasetError: A file is unreadable, or a line is not a valid chunk (file and line named).
    """
    chunks: list[Chunk] = []
    for path in sorted(corpus_dir.glob(f"*{FILE_SUFFIX}")):
        for number, line in enumerate(iter_lines(path), start=1):
            try:
                chunks.append(Chunk.model_validate_json(line))
            except ValidationError as exc:
                msg = f"{path.name}:{number}: not a valid chunk ({exc.error_count()} problems)"
                raise DatasetError(msg) from exc
    return sorted(chunks, key=lambda c: c.chunk_id)


def load_excluded_doc_ids(path: Path) -> frozenset[str]:
    """Read ``source_passage_ids`` of ``indomain_dev_sources.json``.

    Raises:
        DatasetError: The file cannot be read, is too large, or has no ``source_passage_ids`` list.
    """
    try:
        if path.stat().st_size > MAX_EXCLUSION_BYTES:
            msg = f"{path.name}: larger than {MAX_EXCLUSION_BYTES} bytes"
            raise DatasetError(msg)
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        msg = f"cannot read exclusion list {path.name}: {type(exc).__name__}"
        raise DatasetError(msg) from exc
    ids = data.get("source_passage_ids") if isinstance(data, dict) else None
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        msg = f"{path.name}: no source_passage_ids list of strings"
        raise DatasetError(msg)
    return frozenset(ids)


def _eligible(
    chunks: Sequence[Chunk],
    exclude: Collection[str],
    min_tokens: int,
    *,
    german_only: bool = True,
) -> list[Chunk]:
    return [
        c
        for c in sorted(chunks, key=lambda c: c.chunk_id)
        if is_public_text(c)
        and (c.lang is Lang.DE or not german_only)
        and c.doc_id not in exclude
        and estimate_tokens(c.text) >= min_tokens
    ]


def _round_robin(groups: list[list[Chunk]], n: int) -> list[Chunk]:
    """Take from each group in turn, never two chunks of one document."""
    taken: list[Chunk] = []
    docs: set[str] = set()
    positions = [0] * len(groups)
    progress = True
    while len(taken) < n and progress:
        progress = False
        for number, group in enumerate(groups):
            while positions[number] < len(group) and len(taken) < n:
                candidate = group[positions[number]]
                positions[number] += 1
                if candidate.doc_id not in docs:
                    docs.add(candidate.doc_id)
                    taken.append(candidate)
                    progress = True
                    break
    return taken


def sample_chunks(
    chunks: Sequence[Chunk],
    n: int,
    rng: np.random.Generator,
    *,
    tenants: Collection[str] | None = None,
    exclude_doc_ids: Collection[str] = frozenset(),
    min_tokens: int = MIN_TOKENS,
) -> list[Chunk]:
    """Draw up to ``n`` chunks per tenant, stratified by source, one chunk per document.

    Args:
        chunks: The corpus chunks.
        n: Chunks per tenant.
        rng: Seeded generator; the same seed gives the same list.
        tenants: Only these tenants (default: all).
        exclude_doc_ids: Documents never sampled (the in-domain dev set).
        min_tokens: Shortest chunk that is sampled.

    Returns:
        The chunks, tenants in sorted order; a tenant with fewer eligible documents gives fewer.
    """
    pool = [
        c
        for c in _eligible(chunks, exclude_doc_ids, min_tokens)
        if tenants is None or c.tenant in tenants
    ]
    out: list[Chunk] = []
    for tenant in sorted({c.tenant for c in pool}):
        by_source: dict[str, list[Chunk]] = {}
        for c in pool:
            if c.tenant == tenant:
                by_source.setdefault(c.source, []).append(c)
        groups = [
            [by_source[s][i] for i in rng.permutation(len(by_source[s]))] for s in sorted(by_source)
        ]
        out.extend(_round_robin(groups, n))
    return out


def _section_order(chunk: Chunk) -> tuple[str, str, int, str] | None:
    """Sort key of a law chunk inside its law: ``(tenant, law, number, chunk_id)``."""
    cite = parse_one(chunk.citation_key) if chunk.citation_key else None
    if cite is None:
        return None
    match = _LEADING_NUMBER.match(cite.number)
    return (chunk.tenant, cite.law, int(match.group()) if match else 0, chunk.chunk_id)


def _neighbour_pairs(pool: Sequence[Chunk]) -> list[ChunkPair]:
    """Consecutive paragraphs of one law (different documents, same tenant)."""
    keyed = [(k, c) for c in pool if (k := _section_order(c)) is not None]
    keyed.sort(key=lambda item: item[0])
    pairs: list[ChunkPair] = []
    for (key_a, a), (key_b, b) in pairwise(keyed):
        if key_a[:2] == key_b[:2] and a.doc_id != b.doc_id:
            pairs.append((a, b))
    return pairs


def _edge_pairs(pool: Sequence[Chunk], graph: Mapping[str, Sequence[str]]) -> list[ChunkPair]:
    """A law paragraph and a decision (same tenant) that cites it in the citation graph."""
    laws: dict[tuple[str, str], list[Chunk]] = {}
    for c in pool:
        if c.citation_key:
            laws.setdefault((c.tenant, c.citation_key), []).append(c)
    pairs: list[ChunkPair] = []
    for decision in pool:
        for key in graph.get(decision.doc_id, ()):
            pairs.extend((law, decision) for law in laws.get((decision.tenant, key), ()))
    return [p for p in pairs if p[0].doc_id != p[1].doc_id]


def _pick_disjoint(
    candidates: list[ChunkPair], n: int, rng: np.random.Generator
) -> list[ChunkPair]:
    """Seeded choice of pairs that share no chunk and no licence conflict."""
    out: list[ChunkPair] = []
    used: set[str] = set()
    for index in rng.permutation(len(candidates)):
        a, b = candidates[index]
        if len(out) >= n:
            break
        if used & {a.chunk_id, b.chunk_id} or license_config_of([a, b]) is None:
            continue
        used |= {a.chunk_id, b.chunk_id}
        out.append((a, b))
    return out


def sample_multi_hop_pairs(
    chunks: Sequence[Chunk],
    n: int,
    rng: np.random.Generator,
    *,
    graph: Mapping[str, Sequence[str]] | None = None,
    exclude_doc_ids: Collection[str] = frozenset(),
    min_tokens: int = MIN_TOKENS,
) -> list[ChunkPair]:
    """Draw up to ``n`` multi-hop pairs: neighbouring paragraphs of one law, or law + decision.

    Args:
        chunks: The corpus chunks.
        n: Number of pairs.
        rng: Seeded generator.
        graph: Decision ``doc_id`` -> cited law keys (``load_citation_graph``); None = no edges.
        exclude_doc_ids: Documents never sampled.
        min_tokens: Shortest chunk that is sampled.

    Returns:
        Pairs of two different chunks of one tenant; no chunk occurs twice over all pairs.
    """
    pool = _eligible(chunks, exclude_doc_ids, min_tokens)
    candidates = _neighbour_pairs(pool) + _edge_pairs(pool, graph or {})
    return _pick_disjoint(candidates, n, rng)


def sample_cross_lingual_pairs(
    chunks: Sequence[Chunk],
    n: int,
    rng: np.random.Generator,
    *,
    exclude_doc_ids: Collection[str] = frozenset(),
    min_tokens: int = 1,
) -> list[ChunkPair]:
    """Draw up to ``n`` pairs ``(German chunk, English chunk)`` of one ``parallel_id``.

    The chunks of a parallel document are aligned by their position (``#k``); a parallel id whose
    two languages have a different number of chunks is skipped, since the alignment is unknown.
    """
    pool = [
        c
        for c in _eligible(chunks, exclude_doc_ids, min_tokens, german_only=False)
        if c.parallel_id
    ]
    groups: dict[tuple[str, str], dict[str, list[Chunk]]] = {}
    for c in pool:
        groups.setdefault((c.tenant, c.parallel_id or ""), {}).setdefault(c.lang.value, []).append(
            c
        )
    candidates: list[ChunkPair] = []
    for langs in groups.values():
        de, en = langs.get("de", []), langs.get("en", [])
        if de and len(de) == len(en):
            candidates.extend(zip(de, en, strict=True))
    return _pick_disjoint(candidates, n, rng)
