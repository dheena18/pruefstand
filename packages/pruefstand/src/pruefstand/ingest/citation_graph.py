"""``load_citation_graph``: OLDP citation edges -> law citation keys per decision (T2.3 S6).

The graph of the pinned sample (``data/raw/hf/oldp_citation_graph``, one row per edge) names a
decision only by its ``slug`` (``laghe-2014-02-26-2-sa-37213``). The numeric ``id`` that makes
``oldp-<id>`` lives in the decisions dump, so the slugs are resolved against the sibling directory
``oldp_decisions`` (or ``decisions_dir``); reading that directory takes only its ``id`` and
``slug`` columns. Only ``Case -> Law`` edges are used (``Case -> Case`` and ``Law -> Law`` edges are
not citations of a statute by a decision). An edge whose decision is not in the decisions dump is
counted as ``unresolved`` and left out (the 1k graph sample and the 1k decisions sample overlap
in only a few decisions; the summary log line shows the numbers).

A law key is ``core.citations.normalise`` of ``"<to_law_section> <to_law_book_code>"``
(``§ 622`` + ``BGB`` -> ``§ 622 BGB``, ``Artikel 3`` + ``Grundgesetz`` -> ``Art. 3 GG``). A code the
citation parser does not know (``FMStFG``, ``AO 1977``) is kept as ``"§ 5 FMStFG"`` and logged once
per distinct code (event ``citation_unknown_law``). The result maps each decision to its distinct
keys, sorted, and is stable across runs.
"""

from collections.abc import Iterator
from pathlib import Path

from pruefstand.core.citations import normalise, parse_one
from pruefstand.core.ids import DocId
from pruefstand.core.logging import get_logger
from pruefstand.ingest.records import (
    OldpDataError,
    OldpLimits,
    Problem,
    data_files,
    iter_rows,
)

_log = get_logger(__name__)
_MAX_FIELD_CHARS = 100
_GRAPH_COLUMNS = ("from_slug", "from_type", "to_type", "to_law_book_code", "to_law_section")


def _slug_ids(decisions_dir: Path, limits: OldpLimits, problems: list[Problem]) -> dict[str, int]:
    ids: dict[str, int] = {}
    for path in data_files(decisions_dir):
        for row in iter_rows(path, ("id", "slug"), limits, problems):
            number, slug = row.get("id"), row.get("slug")
            if isinstance(number, int) and not isinstance(number, bool) and isinstance(slug, str):
                ids.setdefault(slug, number)
    return ids


def _edges(
    raw_dir: Path, limits: OldpLimits, problems: list[Problem]
) -> Iterator[dict[str, object]]:
    rows = 0
    for path in data_files(raw_dir):
        for row in iter_rows(path, _GRAPH_COLUMNS, limits, problems):
            rows += 1
            if rows > limits.max_rows:
                _log.warning("citation_graph_truncated", max_rows=limits.max_rows)
                return
            yield row


def _text(value: object) -> str:
    text = " ".join(value.split()) if isinstance(value, str) else ""
    return text if len(text) <= _MAX_FIELD_CHARS else ""


def _law_key(section: str, code: str, unknown: set[str]) -> str:
    citation = parse_one(f"{section} {code}")
    if citation is not None:
        return normalise(citation)
    if code not in unknown:
        unknown.add(code)
        _log.warning("citation_unknown_law", law=code, example=f"{section} {code}")
    return f"{section} {code}"


def load_citation_graph(
    raw_dir: Path, *, decisions_dir: Path | None = None, limits: OldpLimits | None = None
) -> dict[DocId, tuple[str, ...]]:
    """Map every decision of the citation graph to the laws it cites.

    Args:
        raw_dir: ``data/raw/hf/oldp_citation_graph`` (parquet or JSON lines of edges).
        decisions_dir: The decisions dump used to turn slugs into ids; default: the sibling
            ``oldp_decisions`` of ``raw_dir``.
        limits: Size limits (default :class:`~pruefstand.ingest.records.OldpLimits`).

    Returns:
        ``{"oldp-123": ("§ 1 KSchG", "§ 622 BGB")}``: the distinct normalised law keys per
        decision, sorted; decisions without a resolvable ``Case -> Law`` edge are absent.

    Raises:
        OldpDataError: ``raw_dir`` or the decisions directory is not a directory.
    """
    limits = limits or OldpLimits()
    if not raw_dir.is_dir():
        msg = f"not a directory: {raw_dir}"
        raise OldpDataError(msg)
    problems: list[Problem] = []
    slug_ids = _slug_ids(decisions_dir or raw_dir.parent / "oldp_decisions", limits, problems)
    keys: dict[int, set[str]] = {}
    unknown: set[str] = set()
    edges = unresolved = 0
    for row in _edges(raw_dir, limits, problems):
        section, code = _text(row.get("to_law_section")), _text(row.get("to_law_book_code"))
        if row.get("from_type") != "Case" or row.get("to_type") != "Law" or not (section and code):
            continue
        number = slug_ids.get(_text(row.get("from_slug")))
        if number is None:
            unresolved += 1
            continue
        edges += 1
        keys.setdefault(number, set()).add(_law_key(section, code, unknown))
    _log.info(
        "citation_graph_loaded",
        decisions=len(keys), edges=edges, unresolved=unresolved, problems=len(problems),
    )  # fmt: skip
    return {DocId(f"oldp-{n}"): tuple(sorted(keys[n])) for n in sorted(keys)}
