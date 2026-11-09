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

from pathlib import Path

from pruefstand.core.citations import normalise, parse_one
from pruefstand.core.ids import DocId
from pruefstand.core.logging import get_logger
from pruefstand.ingest.records import (
    OldpDataError,
    OldpLimits,
    Problem,
    ProblemLog,
    data_files,
    iter_dir_rows,
    valid_id,
)

_log = get_logger(__name__)
_MAX_FIELD_CHARS = 100
_GRAPH_COLUMNS = ("from_slug", "from_type", "to_type", "to_law_book_code", "to_law_section")


def _slug_ids(decisions_dir: Path, limits: OldpLimits, problems: list[Problem]) -> dict[str, int]:
    ids: dict[str, int] = {}
    files = data_files(decisions_dir)
    for _, row in iter_dir_rows(files, ("id", "slug"), limits, problems):
        number, slug = valid_id(row.get("id")), row.get("slug")
        if number is not None and isinstance(slug, str):
            ids.setdefault(slug, number)
    return ids


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


def _check_outcome(
    raw_dir: Path, counts: tuple[int, int, int], problems: ProblemLog, before: tuple[int, int]
) -> None:
    """Fail closed: damaged input and unresolvable edges are errors, an empty graph is not.

    Args:
        raw_dir: The edge directory.
        counts: ``(rows, edges, unresolved)`` of this load.
        problems: The log; only problems counted after ``before`` of it belong to this load, so
            a reused log does not make an empty graph an error (T2.3a).
        before: ``(problems.total, len(problems))`` at the start of the load.
    """
    rows, edges, unresolved = counts
    total, stored = before
    if rows == 0 and problems.total > total:
        first = problems[stored] if len(problems) > stored else problems[-1]
        msg = f"no readable edge row in {raw_dir}: {first.kind} ({first.source})"
        raise OldpDataError(msg)
    if edges == 0 and unresolved > 0:
        msg = f"none of {unresolved} Case->Law edges resolve to a decision (wrong decisions dump?)"
        raise OldpDataError(msg)


def load_citation_graph(
    raw_dir: Path,
    *,
    decisions_dir: Path | None = None,
    limits: OldpLimits | None = None,
    problems: list[Problem] | None = None,
) -> dict[DocId, tuple[str, ...]]:
    """Map every decision of the citation graph to the laws it cites.

    Args:
        raw_dir: ``data/raw/hf/oldp_citation_graph`` (parquet or JSON lines of edges).
        decisions_dir: The decisions dump used to turn slugs into ids; default: the sibling
            ``oldp_decisions`` of ``raw_dir``.
        limits: Size limits (default :class:`~pruefstand.ingest.records.OldpLimits`).
        problems: Optional list the counted file/row problems are appended to (``bad_file``,
            ``bad_json``, ``row_group_too_large``, ``too_many_rows``, ...), so a caller can tell
            damage or truncation from emptiness. A :class:`~pruefstand.ingest.records.ProblemLog`
            also receives the exact counts; a plain list gets the first examples per kind.

    Returns:
        ``{"oldp-123": ("§ 1 KSchG", "§ 622 BGB")}``: the distinct normalised law keys per
        decision, sorted; decisions without a resolvable ``Case -> Law`` edge are absent.

    Raises:
        OldpDataError: ``raw_dir`` or the decisions directory is not a directory, ``raw_dir`` has
            no readable file or no readable row (fail closed), or no ``Case -> Law`` edge can be
            resolved to a decision.
    """
    limits = limits or OldpLimits()
    if not raw_dir.is_dir():
        msg = f"not a directory: {raw_dir}"
        raise OldpDataError(msg)
    log = problems if isinstance(problems, ProblemLog) else ProblemLog()
    try:
        return _load(raw_dir, decisions_dir, limits, log)
    finally:
        if problems is not None and problems is not log:
            problems.extend(log)


def _load(
    raw_dir: Path, decisions_dir: Path | None, limits: OldpLimits, problems: ProblemLog
) -> dict[DocId, tuple[str, ...]]:
    before = (problems.total, len(problems))
    slug_ids = _slug_ids(decisions_dir or raw_dir.parent / "oldp_decisions", limits, problems)
    keys: dict[int, set[str]] = {}
    unknown: set[str] = set()
    edges = unresolved = rows = 0
    if not data_files(raw_dir):
        msg = f"no readable parquet or jsonl file in {raw_dir}"
        raise OldpDataError(msg)
    for _, row in iter_dir_rows(data_files(raw_dir), _GRAPH_COLUMNS, limits, problems):
        rows += 1
        section, code = _text(row.get("to_law_section")), _text(row.get("to_law_book_code"))
        if row.get("from_type") != "Case" or row.get("to_type") != "Law" or not (section and code):
            continue
        number = slug_ids.get(_text(row.get("from_slug")))
        if number is None:
            unresolved += 1
            continue
        edges += 1
        keys.setdefault(number, set()).add(_law_key(section, code, unknown))
    _check_outcome(raw_dir, (rows, edges, unresolved), problems, before)
    _log.info(
        "citation_graph_loaded",
        decisions=len(keys), edges=edges, unresolved=unresolved, problems=problems.total,
    )  # fmt: skip
    return {DocId(f"oldp-{n}"): tuple(sorted(keys[n])) for n in sorted(keys)}
