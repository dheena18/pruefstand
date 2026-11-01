"""Parallel ids and the DE/EN alignment checks (T2.4).

The ``parallel_id`` (:func:`pruefstand.ingest.eurlex_blocks.parallel_id`) is
``<celex>:<block id>``: ``32016R0679:art-6`` for an Article, ``32016R0679:art-6:abs-2`` for the
second paragraph of a long Article that is split, ``32016R0679:rec-1-5`` for a block of recitals.
The id is language-neutral, so a German chunk and its English twin carry the same value and
cross-lingual tests can pair them.
"""

from collections.abc import Sequence

from pruefstand.core.errors import DatasetError
from pruefstand.core.models.corpus import Chunk, Document
from pruefstand.ingest.chunkers.article import ArticleChunker
from pruefstand.ingest.eurlex_blocks import Block

_SHOWN = 10


def _difference(celex: str, de: set[str], en: set[str]) -> str:
    parts = []
    for lang, missing in (("en", sorted(de - en)), ("de", sorted(en - de))):
        if missing:
            more = f" (+{len(missing) - _SHOWN} more)" if len(missing) > _SHOWN else ""
            parts.append(f"missing in {lang}: {', '.join(missing[:_SHOWN])}{more}")
    return f"{celex} is not aligned: " + "; ".join(parts)


def check_aligned(celex: str, de: Sequence[Block], en: Sequence[Block]) -> None:
    """Check that the German and English act have the same Articles and recitals.

    Args:
        celex: CELEX number of the act (named in the error).
        de: Blocks of the German text.
        en: Blocks of the English text.

    Raises:
        DatasetError: The sets of block ids (``art-6``, ``rec-12``) differ; the message names
            the act and the ids missing on each side.
    """
    de_ids, en_ids = {b.block_id for b in de}, {b.block_id for b in en}
    if de_ids != en_ids:
        raise DatasetError(_difference(celex, de_ids, en_ids))


def chunk_aligned(
    chunker: ArticleChunker, de: Document, en: Document
) -> tuple[list[Chunk], list[Chunk]]:
    """Chunk both language versions of an act so that every chunk has a twin.

    Whether an Article is split by paragraph depends on its length, which differs between German
    and English; an Article that is too long in *either* language is split in both.

    Args:
        chunker: The chunker (its limits apply to both documents).
        de: The German document.
        en: The English document.

    Returns:
        ``(german chunks, english chunks)`` with the same ``parallel_id`` multiset.

    Raises:
        DatasetError: The chunks still differ (for example the paragraph counts of a split
            Article differ); the message names the act and the ids.
    """
    split = chunker.long_articles(de) | chunker.long_articles(en)
    de_chunks = chunker.chunk(de, force_split=split)
    en_chunks = chunker.chunk(en, force_split=split)
    de_ids = {c.parallel_id for c in de_chunks if c.parallel_id}
    en_ids = {c.parallel_id for c in en_chunks if c.parallel_id}
    if de_ids != en_ids or len(de_chunks) != len(en_chunks):
        celex = de.metadata.get("celex", str(de.doc_id))
        raise DatasetError(_difference(celex, de_ids, en_ids))
    return de_chunks, en_chunks
