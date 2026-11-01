"""``ArticleChunker``: one chunk per Article and per block of recitals (T2.4).

Input is the document text written by the EUR-Lex loader (:mod:`pruefstand.ingest.eurlex_blocks`).

* **Recitals** are grouped ``recital_group`` (default 5) at a time: ``section="Erwägungsgründe
  1–5"`` / ``"Recitals 1–5"``, ``parallel_id="<celex>:rec-1-5"`` (a lone last recital is
  ``"Erwägungsgrund 10"`` / ``rec-10``). They have no ``citation_key``.
* **Articles** become one chunk each: ``citation_key`` is the canonical German key
  (``"Art. 6 DSGVO"``, also for the English text), ``parallel_id="<celex>:art-6"``, ``section``
  ``None``. An Article whose body has more than ``max_tokens`` tokens (default 1 500) and at least
  two numbered paragraphs is split into one chunk per paragraph: ``section="Art. 6 Abs. 1"``,
  ``parallel_id="<celex>:art-6:abs-1"``, same ``citation_key``. A paragraph is never cut.

Paragraph markers are ``N.`` or ``(N)`` at the start of a line (the German text uses ``(N)``, the
English ``N.``); the body must start with the marker of paragraph 1 and the numbers must run
1, 2, 3, ... without gaps, so a list inside a paragraph that restarts at 1 is not a new paragraph,
and an Article that opens with an unnumbered sentence (``Im Sinne dieser Verordnung ...:`` followed
by definitions) is a list, not paragraphs, and is never split.

Whether to split depends on the language (German is longer), so :meth:`ArticleChunker.chunk` takes
``force_split``: :func:`pruefstand.ingest.align.chunk_aligned` passes the Articles that are long in
either language, which keeps the German and English chunk lists aligned.
"""

import re
from collections.abc import Collection

from pruefstand.core.citations import Citation, normalise
from pruefstand.core.enums import Lang
from pruefstand.core.errors import DatasetError
from pruefstand.core.ids import ChunkId
from pruefstand.core.models.corpus import Chunk, Document
from pruefstand.ingest.eurlex_blocks import Block, parallel_id, parse_blocks
from pruefstand.ingest.text import count_tokens

DEFAULT_MAX_TOKENS = 1500
DEFAULT_RECITAL_GROUP = 5
_DOT = re.compile(r"(\d{1,3})\.\s")
_PAREN = re.compile(r"\((\d{1,3})\)\s")
_Piece = tuple[str, str | None, str | None, str]
_ARTICLE_WORD = {Lang.DE: "Artikel", Lang.EN: "Article"}
_RECITAL_WORDS = {Lang.DE: ("Erwägungsgrund", "Erwägungsgründe"), Lang.EN: ("Recital", "Recitals")}


def split_paragraphs(body: str) -> list[tuple[int, str]]:
    r"""Split an Article body at paragraph markers into ``(number, text)`` pairs.

    The body must *start* with the marker of paragraph 1: text before it means the numbered lines
    are a list (definitions, amendments) and not paragraphs, so nothing is split.

    Args:
        body: The body, one paragraph or list item per line.

    Returns:
        The paragraphs numbered 1, 2, 3, ...; empty when the body does not start with ``1.`` or
        ``(1)``.

    Examples:
        >>> split_paragraphs("1. Eins.\n(a) Liste\n2. Zwei.\n1. Liste")
        [(1, '1. Eins.\n(a) Liste'), (2, '2. Zwei.\n1. Liste')]
        >>> split_paragraphs("(1) Eins.\n(2) Zwei.")
        [(1, '(1) Eins.'), (2, '(2) Zwei.')]
        >>> split_paragraphs("Im Sinne dieser Verordnung:\n(1) Erstens;\n(2) Zweitens.")
        []
    """
    return _split(body, _DOT) or _split(body, _PAREN)


def _split(body: str, marker: re.Pattern[str]) -> list[tuple[int, str]]:
    parts: list[list[str]] = []
    for line in body.split("\n"):
        found = marker.match(line)
        if found is not None and int(found.group(1)) == len(parts) + 1:
            parts.append([line])
        elif parts:
            parts[-1].append(line)
        else:
            return []
    return [(i, "\n".join(lines)) for i, lines in enumerate(parts, start=1)]


def _paragraph_label(lang: Lang, number: int) -> str:
    return f"({number})" if lang is Lang.EN else f" Abs. {number}"


class ArticleChunker:
    """Chunker for EUR-Lex documents (see the module docstring).

    Args:
        max_tokens: An Article body with more tokens is split by paragraph; must be positive.
        recital_group: Recitals per chunk; must be positive.

    Raises:
        ValueError: A parameter is not positive.
    """

    def __init__(
        self, max_tokens: int = DEFAULT_MAX_TOKENS, recital_group: int = DEFAULT_RECITAL_GROUP
    ) -> None:
        if max_tokens < 1:
            msg = "max_tokens must be positive"
            raise ValueError(msg)
        if recital_group < 1:
            msg = "recital_group must be positive"
            raise ValueError(msg)
        self.max_tokens = max_tokens
        self.recital_group = recital_group

    def long_articles(self, doc: Document) -> frozenset[str]:
        """Return the numbers of the Articles of ``doc`` whose body exceeds ``max_tokens``."""
        return frozenset(
            b.number
            for b in parse_blocks(doc.text)
            if b.kind == "art" and count_tokens(b.body) > self.max_tokens
        )

    def chunk(self, doc: Document, *, force_split: Collection[str] = frozenset()) -> list[Chunk]:
        """Split ``doc`` into recital blocks and Articles.

        Args:
            doc: A document from :class:`~pruefstand.ingest.eurlex.EurLexLoader`.
            force_split: Article numbers to split by paragraph even when short.

        Returns:
            The chunks in document order (recitals first); empty when the text is blank.

        Raises:
            DatasetError: ``doc.metadata`` has no ``celex``.
        """
        blocks = parse_blocks(doc.text)
        if not blocks:
            return []
        if "celex" not in doc.metadata:
            msg = f"{doc.doc_id}: document metadata has no celex"
            raise DatasetError(msg)
        celex = doc.metadata["celex"]
        recitals = [b for b in blocks if b.kind == "rec"]
        pieces = self._recital_pieces(doc, celex, recitals)
        for block in blocks:
            if block.kind == "art":
                pieces.extend(self._article_pieces(doc, celex, block, force_split))
        return [
            Chunk(
                chunk_id=ChunkId(f"{doc.doc_id}#{index}"),
                doc_id=doc.doc_id,
                tenant=doc.tenant,
                lang=doc.lang,
                text=text,
                citation_key=key,
                section=section,
                parallel_id=pid,
                version_date=doc.version_date,
                license=doc.license,
                source=doc.source,
            )
            for index, (text, key, section, pid) in enumerate(pieces)
        ]

    def _recital_pieces(self, doc: Document, celex: str, recitals: list[Block]) -> list[_Piece]:
        single, plural = _RECITAL_WORDS[doc.lang]
        pieces: list[_Piece] = []
        for start in range(0, len(recitals), self.recital_group):
            group = recitals[start : start + self.recital_group]
            first, last = group[0].number, group[-1].number
            span = first if first == last else f"{first}–{last}"
            label = f"{single if first == last else plural} {span}"
            pid = parallel_id(celex, f"rec-{first}" if first == last else f"rec-{first}-{last}")
            text = "\n".join([label, *(b.body for b in group)])
            pieces.append((text, None, label, pid))
        return pieces

    def _article_pieces(
        self, doc: Document, celex: str, block: Block, force_split: Collection[str]
    ) -> list[_Piece]:
        key = None
        if doc.law_abbrev is not None:
            key = normalise(Citation(kind="art", number=block.number, law=doc.law_abbrev))
        word = _ARTICLE_WORD[doc.lang]
        head = f"{word} {block.number}"
        paragraphs: list[tuple[int, str]] = []
        if block.number in force_split or count_tokens(block.body) > self.max_tokens:
            paragraphs = split_paragraphs(block.body)
        title = f" – {block.title}" if block.title else ""
        if len(paragraphs) < 2:
            text = f"{head}{title}\n{block.body}".rstrip()
            return [(text, key, None, parallel_id(celex, block.block_id))]
        return [
            (
                f"{head}{_paragraph_label(doc.lang, n)}{title}\n{text}",
                key,
                f"Art. {block.number} Abs. {n}",
                parallel_id(celex, block.block_id, n),
            )
            for n, text in paragraphs
        ]
