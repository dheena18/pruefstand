"""The parts of the spot-check app that need no browser (T4.7a): sample, source view, decisions.

The app (``app.py``) only draws what this module returns. Nothing here writes into the dataset
directory; decisions go to ``spotcheck_decisions.jsonl`` in the review work directory.
"""

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from pruefstand.core.citations import extract_citations, parse_one
from pruefstand.core.config import DatasetBuildConfig
from pruefstand.core.models.corpus import Chunk
from pruefstand.core.models.dataset import ReviewItem, SpotDecision
from pruefstand.core.models.testcase import TestCase
from pruefstand.dataset.io import read_dataset
from pruefstand.dataset.sampling import load_chunks
from pruefstand.pipeline.review_run import (
    SPOT_DECISIONS,
    SPOT_SAMPLE,
    dataset_dir,
    read_decisions,
    read_items,
    review_dir,
    write_spotcheck_sample,
)

REVIEWER_PREFIX = "owner-spotcheck:"
_MARKER = re.compile(r"(?<!\w)\((\d+[a-z]?)\)\s")
NONE, ABSATZ, EVIDENCE = 0, 1, 2


@dataclass(frozen=True)
class Segment:
    """A piece of the source text; ``level`` is 0 (plain), 1 (the cited Absatz) or 2 (evidence)."""

    text: str
    level: int


@dataclass(frozen=True)
class SourceView:
    """One source chunk with its cited Absatz (and the evidence span inside it) marked."""

    chunk_id: str
    citation_key: str | None
    segments: tuple[Segment, ...]


@dataclass(frozen=True)
class SampleItem:
    """What the app shows for one case: the case, the model's verdict and the source views."""

    case: TestCase
    item: ReviewItem | None
    views: tuple[SourceView, ...]


def cited_absaetze(case: TestCase) -> dict[str, set[str]]:
    """Return the Absätze each gold citation names, by ``<number> <law>`` of the provision."""
    found: dict[str, set[str]] = {}
    for gold in case.gold_citations:
        for c in extract_citations(gold):
            absaetze = found.setdefault(f"{c.number} {c.law}", set())
            if c.absatz:
                absaetze.add(c.absatz)
    return found


def _find(text: str, evidence: str | None) -> tuple[int, int] | None:
    """Locate ``evidence`` in ``text`` ignoring differences in whitespace."""
    if not evidence or not evidence.split():
        return None
    match = re.search(r"\s+".join(re.escape(w) for w in evidence.split()), text)
    return (match.start(), match.end()) if match else None


def segments_of(text: str, absatz: str | None, evidence: str | None) -> tuple[Segment, ...]:
    """Split ``text`` into plain, Absatz and evidence segments.

    Args:
        text: The chunk text.
        absatz: The cited Absatz (``"2"``), or None when the citation names none.
        evidence: The case's verbatim evidence span, or None.

    Returns:
        Segments that join back to ``text``. The Absatz that starts with ``(<absatz>)`` is marked
        ``ABSATZ``; the evidence span inside it ``EVIDENCE``. Without a matching Absatz marker only
        the evidence span is marked; a text with neither is one plain segment.

    Examples:
        >>> [(s.text, s.level) for s in segments_of("(1) Eins. (2) Zwei.", "2", None)]
        [('(1) Eins. ', 0), ('(2) Zwei.', 1)]
    """
    markers = list(_MARKER.finditer(text))
    chosen = next((m for m in markers if m.group(1) == absatz), None) if absatz else None
    start, end, outer = 0, len(text), NONE
    if chosen is not None:
        later = [m.start() for m in markers if m.start() > chosen.start()]
        start, end, outer = chosen.start(), later[0] if later else len(text), ABSATZ
    inner = text[start:end]
    span = _find(inner, evidence)
    middle = (
        [Segment(inner, outer)]
        if span is None
        else [
            Segment(inner[: span[0]], outer),
            Segment(inner[span[0] : span[1]], EVIDENCE),
            Segment(inner[span[1] :], outer),
        ]
    )
    pieces = [Segment(text[:start], NONE), *middle, Segment(text[end:], NONE)]
    return tuple(s for s in pieces if s.text)


def _chunk_order(chunk: Chunk) -> tuple[str, int]:
    base, _, index = chunk.chunk_id.rpartition("#")
    return base, int(index) if index.isdigit() else 0


def source_views(case: TestCase, chunks: Sequence[Chunk]) -> tuple[SourceView, ...]:
    """Return the chunks of the case's gold documents, the cited Absatz marked in each.

    Chunks whose provision differs from every gold citation are still shown (a wrong citation
    must be visible), without an Absatz mark.
    """
    cited = cited_absaetze(case)
    docs = set(case.gold_doc_ids)
    views: list[SourceView] = []
    for chunk in sorted((c for c in chunks if c.doc_id in docs), key=_chunk_order):
        key = parse_one(chunk.citation_key or "")
        named = f"{key.number} {key.law}" if key else ""
        absaetze = cited.get(named, set())
        absatz = min(absaetze) if absaetze else None
        evidence = case.evidence_span if named in cited else None
        views.append(
            SourceView(
                chunk.chunk_id, chunk.citation_key, segments_of(chunk.text, absatz, evidence)
            )
        )
    return tuple(views)


def load_sample(cfg: DatasetBuildConfig) -> list[SampleItem]:
    """Load the spot-check sample of a build (drawn on first use).

    Raises:
        DatasetError: The dataset cannot be read (from ``pipeline.review_run``).
    """
    sample = review_dir(cfg) / SPOT_SAMPLE
    if not sample.is_file():
        write_spotcheck_sample(cfg)
    ids = [json.loads(x)["id"] for x in sample.read_text("utf-8").splitlines() if x]
    cases = {c.id: c for v in read_dataset(dataset_dir(cfg)).cases.values() for c in v}
    items: Mapping[str, ReviewItem] = {i.case_id: i for i in read_items(cfg)}
    chunks = load_chunks(cfg.corpus_dir)
    return [
        SampleItem(cases[i], items.get(i), source_views(cases[i], chunks))
        for i in ids
        if i in cases
    ]


def pending(sample: Sequence[SampleItem], cfg: DatasetBuildConfig) -> list[SampleItem]:
    """The items without a decision yet, in sample order."""
    done = {d.case_id for d in read_decisions(cfg)}
    return [s for s in sample if s.case.id not in done]


def write_decision(
    cfg: DatasetBuildConfig,
    case_id: str,
    *,
    citation_ok: bool,
    plausible: bool,
    note: str,
    pseudonym: str,
) -> SpotDecision:
    """Append the owner's decision to ``spotcheck_decisions.jsonl`` and return it.

    Raises:
        ValueError: The pseudonym is empty.
    """
    name = pseudonym.strip()
    if not name:
        msg = "enter a pseudonym in the sidebar first"
        raise ValueError(msg)
    decision = SpotDecision(
        case_id=case_id,
        citation_ok=citation_ok,
        plausible=plausible,
        note=note.strip(),
        reviewer=f"{REVIEWER_PREFIX}{name}",
        ts=datetime.now(UTC),
    )
    path = review_dir(cfg) / SPOT_DECISIONS
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(decision.model_dump_json() + "\n")
    return decision
