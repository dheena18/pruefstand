"""``EurLexLoader``: EUR-Lex HTML (DE, EN) -> one ``Document`` per act and language (T2.4).

``raw_dir`` is ``data/raw/eurlex`` (T2.1 layout): ``<raw_dir>/<celex>/{de,en}.html``, fetched from
the Publications Office CELLAR. For every act of :mod:`pruefstand.ingest.eurlex_acts` two
documents are yielded, German first: ``doc_id`` ``eurlex-<celex>-<lang>``,
``tenant="unassigned"`` (T2.5 assigns tenants), ``source="eurlex:<celex>"``, ``law_abbrev`` the
canonical abbreviation (``DSGVO``, from ``law_aliases.yaml``), ``license="EU-2011/833"``,
``version_date`` the Official Journal publication date of the act (the files are the as-published
text, not a consolidated version). ``metadata`` holds ``celex``, ``citation_en`` (``"GDPR"``),
``attribution``, ``layout`` (``eli``, ``flat`` or ``legacy``) and ``content_hash``. ``text`` is
the block format of :mod:`pruefstand.ingest.eurlex_blocks`, chunked by
:class:`~pruefstand.ingest.chunkers.article.ArticleChunker`.

Nothing raises past the loader for bad input. A directory that is not one of the 20 acts, a missing
file, an unsafe or unreadable file, a file without Articles, or a German and English text whose
Articles or recitals do not match (:func:`pruefstand.ingest.align.check_aligned`) is recorded in
``loader.stats`` and the act is skipped (both languages: a half-loaded pair would break the
cross-lingual tests). The loader checks Article and recital sets only; whether the *chunks* line
up (paragraph splits of long Articles) is checked by
:func:`pruefstand.ingest.align.chunk_aligned`, which T2.5 must call for every (German, English)
pair instead of chunking each document alone. Run
``python -m pruefstand.ingest.eurlex <raw_dir> --stats`` for the counts;
the exit code is 1 when anything was counted.
"""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from pruefstand.core.enums import Lang
from pruefstand.core.errors import DatasetError
from pruefstand.core.hashing import stable_hash
from pruefstand.core.ids import DocId, TenantId
from pruefstand.core.logging import get_logger
from pruefstand.core.models.corpus import Document
from pruefstand.ingest.align import check_aligned
from pruefstand.ingest.eurlex_acts import EurLexAct, act_for
from pruefstand.ingest.eurlex_blocks import render_blocks
from pruefstand.ingest.eurlex_parse import (
    TOO_LARGE,
    EurLexLimits,
    EurLexParseError,
    ParsedAct,
    parse_act,
)

_log = get_logger(__name__)
LICENSE = "EU-2011/833"
ATTRIBUTION = "© European Union, https://eur-lex.europa.eu"
UNASSIGNED = TenantId("unassigned")
_URL = "https://eur-lex.europa.eu/legal-content/{lang}/TXT/?uri=CELEX:{celex}"
_LANGS = (Lang.DE, Lang.EN)


@dataclass(frozen=True)
class Problem:
    """One counted problem: the act (CELEX or directory name), a kind and a detail."""

    celex: str
    kind: str
    detail: str


@dataclass
class EurLexStats:
    """Counts of one load.

    Attributes:
        acts: Acts loaded in both languages (the CLI subtracts acts whose chunks misalign).
        misaligned_acts: Acts skipped (or flagged by the CLI) because DE and EN do not match.
        problems: Every counted problem in order.
    """

    acts: int = 0
    misaligned_acts: int = 0
    problems: list[Problem] = field(default_factory=list)

    def add_problem(self, celex: str, kind: str, detail: str) -> None:
        """Record a problem; ``misaligned`` ones also count in ``misaligned_acts``."""
        if kind == "misaligned":
            self.misaligned_acts += 1
        self.problems.append(Problem(celex, kind, detail))
        _log.warning("eurlex_problem", celex=celex, kind=kind, detail=detail)

    @property
    def error_count(self) -> int:
        """Number of counted problems."""
        return len(self.problems)


class EurLexLoader:
    """Load the pinned EUR-Lex acts (see the module docstring).

    Args:
        limits: Safety limits per file.
        expected: CELEX numbers that must be present; every missing one is a ``missing_act``.

    Attributes:
        stats: Counts and problems, filled while :meth:`load` is consumed.
    """

    def __init__(
        self, *, limits: EurLexLimits | None = None, expected: Sequence[str] | None = None
    ) -> None:
        self.limits = limits or EurLexLimits()
        self.expected = tuple(expected or ())
        self.stats = EurLexStats()

    def load(self, raw_dir: Path) -> Iterator[Document]:
        """Yield the German and English document of every ``<raw_dir>/<celex>/``.

        Args:
            raw_dir: ``data/raw/eurlex``; a missing directory yields nothing.

        Yields:
            Documents in a deterministic order (acts sorted by CELEX, German before English).
        """
        seen: set[str] = set()
        if raw_dir.is_dir():
            for directory in sorted(p for p in raw_dir.iterdir() if p.is_dir()):
                seen.add(directory.name)
                yield from self._load_act(directory)
        for celex in self.expected:
            if celex not in seen:
                self.stats.add_problem(celex, "missing_act", f"no {celex}/ under {raw_dir}")

    def _load_act(self, directory: Path) -> Iterator[Document]:
        celex = directory.name
        act = act_for(celex)
        if act is None:
            self.stats.add_problem(celex, "unknown_act", "CELEX is not one of the 20 pinned acts")
            return
        parsed = self._parse_both(directory, celex)
        if parsed is None:
            return
        try:
            check_aligned(celex, parsed[0].blocks, parsed[1].blocks)
        except DatasetError as err:
            self.stats.add_problem(celex, "misaligned", str(err))
            return
        for lang, one in zip(_LANGS, parsed, strict=True):
            for dup in one.duplicates:
                self.stats.add_problem(celex, "duplicate_block", f"{lang}: {dup}")
        self.stats.acts += 1
        _log.info("eurlex_act_loaded", celex=celex, blocks=len(parsed[0].blocks))
        for lang, one in zip(_LANGS, parsed, strict=True):
            yield self._document(act, lang, one)

    def _parse_both(self, directory: Path, celex: str) -> tuple[ParsedAct, ParsedAct] | None:
        results = []
        for lang in _LANGS:
            path = directory / f"{lang.value}.html"
            try:
                results.append(self._parse_file(path))
            except FileNotFoundError:
                self.stats.add_problem(celex, "missing_file", f"{path.name} not found")
                return None
            except (OSError, EurLexParseError) as err:
                kind = err.kind if isinstance(err, EurLexParseError) else "unreadable"
                self.stats.add_problem(celex, kind, f"{path.name}: {err}")
                return None
        return results[0], results[1]

    def _parse_file(self, path: Path) -> ParsedAct:
        size = path.stat().st_size
        if size > self.limits.max_bytes:
            raise EurLexParseError(TOO_LARGE, f"{size} bytes exceed {self.limits.max_bytes}")
        return parse_act(path.read_bytes(), self.limits)

    @staticmethod
    def _document(act: EurLexAct, lang: Lang, parsed: ParsedAct) -> Document:
        text = render_blocks(parsed.blocks)
        metadata = {
            "celex": act.celex, "citation_en": act.citation_en, "attribution": ATTRIBUTION,
            "layout": parsed.layout, "content_hash": stable_hash(text),
        }  # fmt: skip
        return Document(
            doc_id=DocId(f"eurlex-{act.celex}-{lang.value}"), tenant=UNASSIGNED,
            source=f"eurlex:{act.celex}", lang=lang, title=parsed.title or act.abbrev,
            law_abbrev=act.abbrev, version_date=parsed.published, text=text, license=LICENSE,
            url=_URL.format(lang=lang.value.upper(), celex=act.celex), metadata=metadata,
        )  # fmt: skip


if __name__ == "__main__":
    from pruefstand.ingest.eurlex_cli import main

    raise SystemExit(main())
