r"""``FixedTokenChunker``: token windows with overlap (T2.3), the fallback of decisions.

Windows are counted in the corpus-wide approximate tokens of
:func:`pruefstand.ingest.text.count_tokens` (``\w+`` runs and single symbols; a ``\w`` run also
keeps the combining marks that follow it, so a decomposed ``u`` + U+0308 is one token). The count
is a cheap, model-independent size, not a tokenizer; for NFC text it equals ``count_tokens``.

A window is the exact slice of the source from the start of its first token to the end of its last
token, so line breaks and spacing inside a chunk are those of the document and a boundary never
splits a word or a combining character. With ``max_tokens=M`` and ``overlap=O`` the windows start at
token ``0, M-O, 2(M-O), ...`` and the last one ends at the last token (it may be shorter; a window
that already reaches the end is the last). The scan is one regex pass plus slicing: linear time.
"""

import re
from array import array

from pruefstand.core.ids import ChunkId
from pruefstand.core.models.corpus import Chunk, Document

DEFAULT_MAX_TOKENS = 512
DEFAULT_OVERLAP = 64
_MARKS = r"\u0300-\u036f\u1ab0-\u1aff\u1dc0-\u1dff\u20d0-\u20ff\ufe20-\ufe2f"
_TOKEN = re.compile(rf"\w[\w{_MARKS}]*|[^\w\s]")


def check_window(max_tokens: int, overlap: int) -> None:
    """Validate window parameters.

    Raises:
        ValueError: ``max_tokens`` < 1, or ``overlap`` not in ``0 <= overlap < max_tokens``.
    """
    if max_tokens < 1:
        msg = "max_tokens must be positive"
        raise ValueError(msg)
    if not 0 <= overlap < max_tokens:
        msg = "overlap must satisfy 0 <= overlap < max_tokens"
        raise ValueError(msg)


def token_windows(text: str, max_tokens: int, overlap: int) -> list[str]:
    """Cut ``text`` into overlapping windows of at most ``max_tokens`` tokens.

    Args:
        text: Any text.
        max_tokens: Window size in tokens (at least 1).
        overlap: Tokens shared by neighbouring windows (``0 <= overlap < max_tokens``).

    Returns:
        The windows in order; ``[]`` when the text has no token.

    Raises:
        ValueError: Invalid ``max_tokens`` / ``overlap``.

    Examples:
        >>> token_windows("a b c d e f g", 4, 1)
        ['a b c d', 'd e f g']
        >>> token_windows("", 4, 1)
        []
    """
    check_window(max_tokens, overlap)
    starts = array("I")
    ends = array("I")
    for match in _TOKEN.finditer(text):
        starts.append(match.start())
        ends.append(match.end())
    total = len(starts)
    windows: list[str] = []
    first = 0
    while first < total:
        last = min(first + max_tokens, total)
        windows.append(text[starts[first] : ends[last - 1]])
        if last >= total:
            break
        first += max_tokens - overlap
    return windows


def build_chunk(doc: Document, index: int, section: str | None, text: str) -> Chunk:
    """Build chunk ``<doc_id>#<index>`` of ``doc`` (shared by the decision chunker)."""
    return Chunk(
        chunk_id=ChunkId(f"{doc.doc_id}#{index}"),
        doc_id=doc.doc_id,
        tenant=doc.tenant,
        lang=doc.lang,
        text=text,
        citation_key=doc.metadata.get("citation_key"),
        section=section,
        parallel_id=None,
        version_date=doc.version_date,
        license=doc.license,
        source=doc.source,
    )


class FixedTokenChunker:
    """Chunker that cuts the document text into overlapping token windows (``section=None``).

    Args:
        max_tokens: Window size (default 512).
        overlap: Overlap of neighbouring windows (default 64).

    Raises:
        ValueError: Invalid ``max_tokens`` / ``overlap``.
    """

    def __init__(
        self, max_tokens: int = DEFAULT_MAX_TOKENS, overlap: int = DEFAULT_OVERLAP
    ) -> None:
        check_window(max_tokens, overlap)
        self.max_tokens = max_tokens
        self.overlap = overlap

    def chunk(self, doc: Document) -> list[Chunk]:
        """Split ``doc`` into windows with ids ``<doc_id>#0``, ``#1``, ...

        Args:
            doc: Any document.

        Returns:
            The chunks in order; empty for a blank text.
        """
        windows = token_windows(doc.text, self.max_tokens, self.overlap)
        return [build_chunk(doc, i, None, window) for i, window in enumerate(windows)]
