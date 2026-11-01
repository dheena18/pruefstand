"""``OldpLoader``: Open Legal Data court decisions (pinned 1k sample) -> ``Document`` (T2.3).

``raw_dir`` is ``data/raw/hf/oldp_decisions`` (T2.1 layout): ``*.parquet`` files below the config
directory (``dump-20260520-1k/``) or ``*.jsonl`` files, read in sorted order; the hidden
``.cache`` directory ``snapshot_download`` leaves behind is ignored. Nothing here uses the
Hugging Face cache or the network.

Each record becomes one :class:`~pruefstand.core.models.corpus.Document`: ``doc_id`` ``oldp-<id>``,
``tenant="unassigned"`` (T2.5 assigns tenants), ``lang=de``, ``license="ODbL-1.0"``,
``source="oldp:decisions"``, ``title`` ``"<court> <date> <Aktenzeichen>"``, ``version_date`` the
decision date, ``text`` the HTML of ``content`` as plain lines
(:func:`~pruefstand.ingest.html_text.html_to_text`). ``metadata`` (empty values left out):
``court``,
``court_level``, ``jurisdiction`` (``Arbeitsgericht``, ``Sozialgericht``, ``Zivilgericht``, ...; see
:mod:`pruefstand.ingest.oldp_courts`), ``tenant_domain`` (``labour`` / ``insurance`` / ``other``),
``file_number``, ``ecli``, ``slug``, ``decision_type``.

A record with an empty ``content`` (two of the 1 000 are) is still a document, with empty text and
no chunks, and is counted in ``stats.empty``. Bad input never raises past the loader: a record
without an integer ``id`` or a text ``content``, a duplicate ``id``, an oversized record, a
broken file or HTML the parser rejects is a counted problem in ``stats.problems`` and loading
continues. Run ``python -m pruefstand.ingest.oldp <raw_dir> --stats`` for the counts; the exit code
is 1 when any problem was counted.
"""

import argparse
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from pruefstand.core.enums import Lang
from pruefstand.core.ids import DocId, TenantId
from pruefstand.core.models.corpus import Document
from pruefstand.ingest.chunkers.decision import (
    DecisionSectionChunker,
    dropped_trailer,
    has_named_sections,
)
from pruefstand.ingest.html_text import HtmlTextError, html_to_text
from pruefstand.ingest.oldp_courts import classify_court, tenant_domain
from pruefstand.ingest.records import (
    OldpDataError,
    OldpLimits,
    Problem,
    data_files,
    iter_rows,
)

__all__ = ["OldpDataError", "OldpLimits", "OldpLoader", "OldpStats", "main"]

LICENSE = "ODbL-1.0"
SOURCE = "oldp:decisions"
UNASSIGNED = TenantId("unassigned")
COLUMNS = ("id", "slug", "court", "file_number", "date", "type", "ecli", "content")


@dataclass
class OldpStats:
    """Counters of a load, filled while the loader's iterator is consumed."""

    decisions: int = 0
    empty: int = 0
    problems: list[Problem] = field(default_factory=list)


def _text(value: object) -> str:
    if isinstance(value, date):
        return (value.date() if isinstance(value, datetime) else value).isoformat()
    return " ".join(value.split()) if isinstance(value, str) else ""


def _decision_date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


class OldpLoader:
    """Loader for the OLDP decision sample (see the module docstring).

    Args:
        limits: Size limits; the defaults are far above the 1k sample.

    Attributes:
        stats: Counters of the latest :meth:`load` (reset at its start).
    """

    def __init__(self, limits: OldpLimits | None = None) -> None:
        self.limits = limits or OldpLimits()
        self.stats = OldpStats()

    def load(self, raw_dir: Path) -> Iterator[Document]:
        """Yield one document per decision under ``raw_dir``.

        Args:
            raw_dir: ``data/raw/hf/oldp_decisions``.

        Yields:
            The decisions in file and row order.

        Raises:
            OldpDataError: ``raw_dir`` is not a directory.
        """
        self.stats = OldpStats()
        files = data_files(raw_dir)
        if not files:
            self.stats.problems.append(
                Problem(str(raw_dir), "no_files", "no parquet or jsonl file")
            )
        seen: set[int] = set()
        for path in files:
            for row in iter_rows(path, COLUMNS, self.limits, self.stats.problems):
                if self.stats.decisions >= self.limits.max_documents:
                    detail = f"more than {self.limits.max_documents} decisions"
                    self.stats.problems.append(Problem(path.name, "too_many_documents", detail))
                    return
                doc = self._document(row, path.name, seen)
                if doc is not None:
                    self.stats.decisions += 1
                    self.stats.empty += 0 if doc.text else 1
                    yield doc

    def _fail(self, source: str, kind: str, detail: str) -> None:
        self.stats.problems.append(Problem(source, kind, detail))

    def _document(self, row: dict[str, object], source: str, seen: set[int]) -> Document | None:
        number, content, court = row.get("id"), row.get("content"), row.get("court")
        if isinstance(number, bool) or not isinstance(number, int) or number < 1:
            self._fail(source, "bad_record", f"id is not a positive integer: {number!r}"[:100])
        elif not isinstance(content, str):
            self._fail(f"{source}#{number}", "bad_record", "content is not text")
        elif court is not None and not isinstance(court, dict):
            self._fail(f"{source}#{number}", "bad_record", "court is not an object")
        elif len(content) > self.limits.max_content_chars:
            self._fail(f"{source}#{number}", "content_too_large", f"{len(content)} characters")
        elif number in seen:
            self._fail(f"{source}#{number}", "duplicate_id", f"oldp-{number} seen twice")
        else:
            seen.add(number)
            return self._build(number, content, court or {}, row)
        return None

    def _build(
        self, number: int, content: str, court: dict[str, object], row: dict[str, object]
    ) -> Document | None:
        try:
            text = html_to_text(content)
        except HtmlTextError as error:
            self._fail(f"oldp-{number}", "bad_html", str(error))
            return None
        name = _text(court.get("name"))
        level_field, jurisdiction_field = court.get("level_of_appeal"), court.get("jurisdiction")
        kind = classify_court(
            name,
            jurisdiction_field if isinstance(jurisdiction_field, str) else None,
            level_field if isinstance(level_field, str) else None,
        )
        file_number, day = _text(row.get("file_number")), _text(row.get("date"))
        metadata = {
            "court": name, "court_level": kind.level, "jurisdiction": kind.jurisdiction,
            "tenant_domain": tenant_domain(kind.jurisdiction, text), "file_number": file_number,
            "ecli": _text(row.get("ecli")), "slug": _text(row.get("slug")),
            "decision_type": _text(row.get("type")),
        }  # fmt: skip
        return Document(
            doc_id=DocId(f"oldp-{number}"), tenant=UNASSIGNED, source=SOURCE, lang=Lang.DE,
            title=" ".join(part for part in (name, day, file_number) if part), law_abbrev=None,
            version_date=_decision_date(row.get("date")), text=text, license=LICENSE, url=None,
            metadata={k: v for k, v in metadata.items() if v},
        )  # fmt: skip


def main(argv: Sequence[str] | None = None) -> int:
    """Load every decision under ``raw_dir``, chunk it and print the counts with ``--stats``.

    Args:
        argv: Command line (default: ``sys.argv[1:]``).

    Returns:
        0 when no problem was counted, 1 when any was (the first go to stderr), 2 when
        ``raw_dir`` is not a directory.
    """
    parser = argparse.ArgumentParser(
        prog="python -m pruefstand.ingest.oldp", description="Load the OLDP decisions and count."
    )
    parser.add_argument("raw_dir", type=Path, help="data/raw/hf/oldp_decisions")
    parser.add_argument("--stats", action="store_true", help="print decisions/chunks/no_sections")
    args = parser.parse_args(argv)
    loader, chunker = OldpLoader(), DecisionSectionChunker()
    chunks = no_sections = trailer_chars = 0
    try:
        for doc in loader.load(args.raw_dir):
            chunks += len(chunker.chunk(doc))
            no_sections += 1 if doc.text and not has_named_sections(doc.text) else 0
            trailer_chars += dropped_trailer(doc.text)[1]
    except OldpDataError as error:
        sys.stderr.write(f"error: {error}\n")
        return 2
    stats = loader.stats
    if args.stats:
        line = f"decisions={stats.decisions} chunks={chunks} no_sections={no_sections}"
        sys.stdout.write(f"{line} errors={len(stats.problems)} trailer_chars={trailer_chars}\n")
    for problem in stats.problems[:20]:
        sys.stderr.write(f"error: {problem.source}: {problem.kind}: {problem.detail}\n")
    return 1 if stats.problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
