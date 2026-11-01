"""``GiiXmlLoader``: Gesetze im Internet XML (``xml.zip`` per law) -> ``Document`` per § / Artikel.

``raw_dir`` is ``data/raw/gii`` (T2.1 layout): ``<raw_dir>/<law>/xml.zip``, in sorted order. The
archives are read in memory (never extracted), the XML is parsed with a hardened parser and
streamed norm by norm (see ``ingest/gii/``); one law is held at a time.

Each citable ``<norm>`` becomes one :class:`~pruefstand.core.models.corpus.Document`:
``doc_id`` ``gii-<law slug>-<number>`` (``gii-bgb-622``, ``gii-bgb-626a``; a § nested in an EGBGB
Artikel is ``gii-egbgb-246a-1``), ``tenant="unassigned"`` (T2.5 assigns tenants), ``lang=de``,
``license="§5-UrhG"`` (official works, § 5 UrhG), ``source="gii:<law dir>"``, text from
:mod:`pruefstand.ingest.gii.extract`. ``metadata`` holds ``citation_key``, ``unit`` (``para`` or
``art``), ``jurabk`` (the spelling in the file, e.g. ``BGBEG``), ``doknr``, ``builddate``,
``content_hash`` (``stable_hash`` of the text), ``stand`` (the law's ``Zuletzt geändert durch
...`` remark) and, for nested units, ``article`` and ``section``.

``version_date`` is the ``builddate`` attribute of the norm (the day GII built this consolidated
text, ``YYYYMMDDhhmmss`` -> date), falling back to the ``builddate`` of the document element, else
``None``. It is *not* the date of the last amendment: that remark is free German text
(``Zuletzt geändert durch Art. 6 G v. 23.7.2026 I Nr. 226``) and is kept verbatim in
``metadata["stand"]``. The pinned SHA-256 in ``data/sources.yaml`` fixes the file, so the date is
reproducible for a given pin.

A norm whose number core.citations cannot read (two letters after the digits: KWG § 53ca to
§ 53cq) is counted as skipped (``uncitable``) and logged, never emitted without a key
(follow-up: T1.5a parser).

Nothing raises past the loader for bad input: a broken archive, unsafe or malformed XML, an
unknown law or ``enbez``, an unparsable citation key or a duplicate id is recorded in
``loader.stats.problems`` and loading continues. Run ``python -m pruefstand.ingest.gii_xml
<raw_dir> --stats`` for per-law counts; the exit code is 1 when anything was counted.
"""

import argparse
import re
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from lxml import etree

from pruefstand.core.enums import Lang
from pruefstand.core.hashing import stable_hash
from pruefstand.core.ids import DocId, TenantId
from pruefstand.core.logging import get_logger
from pruefstand.core.models.corpus import Document
from pruefstand.ingest.chunkers.paragraph import ParagraphChunker
from pruefstand.ingest.gii.errors import (
    CitationKeyError,
    GiiParseError,
    UnsafeArchiveError,
    UnsafeXmlError,
)
from pruefstand.ingest.gii.extract import norm_text
from pruefstand.ingest.gii.keys import citation_key, resolve_jurabk, slug_of
from pruefstand.ingest.gii.norms import (
    REPEALED,
    NormMeta,
    Reject,
    Skip,
    Unit,
    classify,
    parse_builddate,
    read_meta,
    read_stand,
)
from pruefstand.ingest.gii.safezip import ZipLimits, read_xml_members
from pruefstand.ingest.gii.stats import GiiStats, LawStats
from pruefstand.ingest.gii.xmlparse import XmlLimits, iter_norms

_log = get_logger(__name__)
LICENSE = "§5-UrhG"
_TWO_LETTERS = re.compile(r"\d[a-z]{2,}\Z")
UNASSIGNED = TenantId("unassigned")


@dataclass
class _Archive:
    """Mutable state of the archive being read."""

    slug: str
    law: str | None = None
    stand: str | None = None
    stats: LawStats = field(default_factory=LawStats)
    seen: set[str] = field(default_factory=set)

    @property
    def name(self) -> str:
        return self.law or self.slug


class GiiXmlLoader:
    """Load the pinned GII law archives as documents (see the module docstring).

    Args:
        zip_limits: Safety limits for the archives.
        xml_limits: Safety limits for the XML.

    Attributes:
        stats: Counts and problems, filled while :meth:`load` is consumed.
    """

    def __init__(
        self, *, zip_limits: ZipLimits | None = None, xml_limits: XmlLimits | None = None
    ) -> None:
        self.zip_limits = zip_limits or ZipLimits()
        self.xml_limits = xml_limits or XmlLimits()
        self.stats = GiiStats()

    def load(self, raw_dir: Path) -> Iterator[Document]:
        """Yield one document per citable norm of every ``<raw_dir>/<law>/xml.zip``.

        Args:
            raw_dir: ``data/raw/gii``; a missing directory yields nothing.

        Yields:
            Documents in a deterministic order (archives sorted by path, norms in file order).
        """
        if not raw_dir.is_dir():
            return
        for zip_path in sorted(raw_dir.glob("*/xml.zip")):
            yield from self._load_archive(zip_path)

    def _load_archive(self, zip_path: Path) -> Iterator[Document]:
        arch = _Archive(slug=zip_path.parent.name)
        try:
            for member, data in read_xml_members(zip_path, self.zip_limits):
                yield from self._load_member(arch, member, data)
        except UnsafeArchiveError as err:
            self.stats.add_problem(arch.name, "unsafe_archive", f"{zip_path.name}: {err}")
        finally:
            self._finish(arch)

    def _load_member(self, arch: _Archive, member: str, data: bytes) -> Iterator[Document]:
        try:
            for norm in iter_norms(data, self.xml_limits):
                doc = self._document(arch, norm)
                if doc is not None:
                    yield doc
        except UnsafeXmlError as err:
            self.stats.add_problem(arch.name, "unsafe_xml", f"{member}: {err}")
        except GiiParseError as err:
            self.stats.add_problem(arch.name, "invalid_xml", f"{member}: {err}")

    def _finish(self, arch: _Archive) -> None:
        if arch.stats.norms:
            self.stats.laws.setdefault(arch.name, arch.stats)
            s = arch.stats
            _log.info(
                "gii_law_loaded", law=arch.name, norms=s.norms, skipped=s.skipped,
                documents=s.documents, errors=s.errors,
            )  # fmt: skip

    def _reject(self, arch: _Archive, kind: str, detail: str) -> None:
        arch.stats.errors += 1
        self.stats.add_problem(arch.name, kind, detail)

    def _learn(self, arch: _Archive, norm: etree._Element, meta: NormMeta) -> date | None:
        """Track the law name and version date; return the version date of this norm."""
        if arch.law is None and (law := resolve_jurabk(meta.jurabk)) is not None:
            arch.law = law
            self.stats.laws[law] = arch.stats
        parent = norm.getparent()
        root_date = parse_builddate(parent.get("builddate") if parent is not None else None)
        version = parse_builddate(meta.builddate) or root_date
        if arch.stats.version_date is None:
            arch.stats.version_date = root_date or version
        return version

    def _document(self, arch: _Archive, norm: etree._Element) -> Document | None:
        meta = read_meta(norm)
        arch.stats.norms += 1
        version = self._learn(arch, norm, meta)
        verdict = classify(meta)
        if isinstance(verdict, Skip):
            if verdict.reason == "header":
                arch.stand = read_stand(norm) or arch.stand
            arch.stats.skip(verdict.reason)
            return None
        if isinstance(verdict, Reject):
            self._reject(arch, verdict.kind, f"{meta.doknr}: {verdict.detail!r}")
            return None
        return self._build(arch, norm, meta, verdict, version)

    def _build(
        self, arch: _Archive, norm: etree._Element, meta: NormMeta, unit: Unit, version: date | None
    ) -> Document | None:
        law = resolve_jurabk(meta.jurabk)
        if law is None:
            self._reject(arch, "unknown_law", f"{meta.doknr}: jurabk {meta.jurabk!r}")
            return None
        text = norm_text(norm)
        if meta.titel.casefold() in REPEALED or text.casefold() in REPEALED:
            arch.stats.skip("repealed")
        elif not text:
            arch.stats.skip("structure" if unit.from_gliederung else "empty")
        else:
            return self._make(arch, meta, unit, law=law, text=text, version=version)
        return None

    def _make(
        self,
        arch: _Archive,
        meta: NormMeta,
        unit: Unit,
        *,
        law: str,
        text: str,
        version: date | None,
    ) -> Document | None:
        try:
            key = citation_key(unit.kind, unit.number, law)
        except CitationKeyError as err:
            if _TWO_LETTERS.search(unit.number):
                # core.citations reads one letter after a number; counted as a skip, never silent
                _log.warning("gii_uncitable_number", law=law, number=unit.number)
                arch.stats.skip("uncitable")
            else:
                self._reject(arch, "bad_citation_key", f"{meta.doknr}: {err}")
            return None
        doc_id = f"gii-{slug_of(law)}-{unit.suffix}"
        if doc_id in arch.seen:
            self._reject(arch, "duplicate_doc_id", f"{meta.doknr}: {doc_id}")
            return None
        arch.seen.add(doc_id)
        arch.stats.documents += 1
        extra = {"article": unit.number, "section": unit.section or ""} if unit.sub else {}
        metadata = {
            "citation_key": key, "unit": unit.kind, "jurabk": meta.jurabk, "doknr": meta.doknr,
            "builddate": meta.builddate, "content_hash": stable_hash(text),
            "stand": arch.stand or "", **extra,
        }  # fmt: skip
        return Document(
            doc_id=DocId(doc_id), tenant=UNASSIGNED, source=f"gii:{arch.slug}", lang=Lang.DE,
            title=meta.titel or key, law_abbrev=law, version_date=version, text=text,
            license=LICENSE, url=None, metadata={k: v for k, v in metadata.items() if v},
        )  # fmt: skip


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m pruefstand.ingest.gii_xml", description="Load the GII laws and count."
    )
    parser.add_argument("raw_dir", type=Path, help="data/raw/gii")
    parser.add_argument("--stats", action="store_true", help="print per-law counts")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Load every law under ``raw_dir``, chunk it and print per-law counts with ``--stats``.

    Args:
        argv: Command line (default: ``sys.argv[1:]``).

    Returns:
        0 when nothing was counted as a problem, else 1 (the first problems go to stderr).
    """
    args = _parser().parse_args(argv)
    loader = GiiXmlLoader()
    chunker = ParagraphChunker()
    for doc in loader.load(args.raw_dir):
        loader.stats.record_chunks(doc.law_abbrev or doc.source, len(chunker.chunk(doc)))
    if args.stats:
        sys.stdout.write(loader.stats.format_table() + "\n")
    for problem in loader.stats.problems[:20]:
        sys.stderr.write(f"error: {problem.law}: {problem.kind}: {problem.detail}\n")
    return 1 if loader.stats.error_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
