"""Chunking step of ``pruefstand ingest`` (T2.5): the right chunker per source."""

from collections.abc import Iterable, Iterator

from pruefstand.core.enums import Lang
from pruefstand.core.errors import DatasetError
from pruefstand.core.models.corpus import Chunk, Document
from pruefstand.ingest.align import chunk_aligned
from pruefstand.ingest.chunkers.article import ArticleChunker
from pruefstand.ingest.chunkers.decision import DecisionSectionChunker
from pruefstand.ingest.chunkers.fixed import FixedTokenChunker
from pruefstand.ingest.chunkers.paragraph import ParagraphChunker


def chunk_documents(docs: Iterable[Document], max_tokens: int) -> Iterator[Chunk]:
    """Chunk documents with the chunker of their source.

    ``gii:`` documents use :class:`ParagraphChunker`, ``eurlex:`` the :class:`ArticleChunker`
    (German and English version of an act are chunked together so every chunk has a twin),
    ``oldp`` the :class:`DecisionSectionChunker`, anything else the :class:`FixedTokenChunker`.

    Args:
        docs: Documents with their tenant set. The German document of an act must be followed
            (not necessarily directly) by its English one, as the EUR-Lex loader yields them.
        max_tokens: Chunk size.

    Yields:
        Chunks in document order.

    Raises:
        DatasetError: An act lacks one language, or its two languages do not align.
    """
    paragraph, article = ParagraphChunker(max_tokens), ArticleChunker(max_tokens)
    decision, fixed = DecisionSectionChunker(max_tokens), FixedTokenChunker(max_tokens)
    waiting: dict[str, Document] = {}
    for doc in docs:
        if doc.source.startswith("eurlex:"):
            celex = doc.metadata.get("celex")
            if celex is None:
                msg = f"{doc.doc_id}: EUR-Lex document without celex metadata"
                raise DatasetError(msg)
            first = waiting.pop(celex, None)
            if first is None:
                waiting[celex] = doc
                continue
            de, en = (first, doc) if first.lang is Lang.DE else (doc, first)
            for chunks in chunk_aligned(article, de, en):
                yield from chunks
        elif doc.source.startswith("gii:"):
            yield from paragraph.chunk(doc)
        elif doc.source.startswith("oldp"):
            yield from decision.chunk(doc)
        else:
            yield from fixed.chunk(doc)
    if waiting:
        msg = f"EUR-Lex act(s) {sorted(waiting)} have only one language"
        raise DatasetError(msg)
