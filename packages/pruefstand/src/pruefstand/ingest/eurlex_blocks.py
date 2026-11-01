r"""The text format of an EUR-Lex ``Document`` and the helpers of loader and chunker (T2.4).

A document holds one act in one language as a sequence of *blocks*, one per recital and one per
Article, each introduced by a marker line::

    \x1eREC 12\t
    (12) Die Verarbeitung ...
    \x1eART 6\tRechtmäßigkeit der Verarbeitung
    1. Die Verarbeitung ist nur rechtmäßig, ...

The marker starts with the ASCII record separator U+001E. :func:`clean` removes every control
character from the source text, so a marker can only be produced by :func:`render_blocks`: input
text can never forge a block boundary. Parsing is one pass over the lines, so it is linear.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from pruefstand.ingest.text import normalise_line

MARK = "\x1e"
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
_HEADER = re.compile(rf"{MARK}(REC|ART) (\S+)\t(.*)\Z")


@dataclass(frozen=True)
class Block:
    """One recital or one Article of an act.

    Attributes:
        kind: ``"rec"`` (recital) or ``"art"`` (Article).
        number: The recital or Article number as printed, lower case (``"6"``, ``"8a"``).
        title: The Article's title (empty for recitals and untitled Articles).
        body: The text, one line per paragraph or list item.
    """

    kind: Literal["rec", "art"]
    number: str
    title: str
    body: str

    @property
    def block_id(self) -> str:
        """Language-neutral id of the block, e.g. ``"art-6"`` or ``"rec-12"``."""
        return f"{self.kind}-{self.number}"


def parallel_id(celex: str, block_id: str, paragraph: int | None = None) -> str:
    """Build the language-neutral ``parallel_id`` of a chunk (see :mod:`pruefstand.ingest.align`).

    Examples:
        >>> parallel_id("32016R0679", "art-6")
        '32016R0679:art-6'
        >>> parallel_id("32016R0679", "art-6", 2)
        '32016R0679:art-6:abs-2'
    """
    base = f"{celex}:{block_id}"
    return base if paragraph is None else f"{base}:abs-{paragraph}"


def clean(text: str) -> str:
    r"""NFC, control characters to spaces, whitespace collapsed to single spaces.

    Examples:
        >>> clean("Artikel\xa06 \x1eART 9\t x")
        'Artikel 6 ART 9 x'
    """
    return normalise_line(_CONTROL.sub(" ", text))


def render_blocks(blocks: Iterable[Block]) -> str:
    r"""Serialise blocks into the document text (see the module docstring).

    Args:
        blocks: Blocks in document order; titles and bodies must come from :func:`clean`.

    Returns:
        The text; empty for no blocks.

    Examples:
        >>> render_blocks([Block("art", "1", "Zweck", "Text.")])
        '\x1eART 1\tZweck\nText.'
    """
    lines: list[str] = []
    for block in blocks:
        lines.append(f"{MARK}{block.kind.upper()} {block.number}\t{block.title}")
        if block.body:
            lines.append(block.body)
    return "\n".join(lines)


def parse_blocks(text: str) -> list[Block]:
    r"""Parse the text written by :func:`render_blocks`; text before the first marker is ignored.

    Args:
        text: A document text.

    Returns:
        The blocks in order (empty when there is no marker).

    Examples:
        >>> blocks = parse_blocks("\x1eART 1\tZweck\nText.\n\x1eREC 2\t\n(2) Grund.")
        >>> [(b.block_id, b.title, b.body) for b in blocks]
        [('art-1', 'Zweck', 'Text.'), ('rec-2', '', '(2) Grund.')]
    """
    heads: list[tuple[Literal["rec", "art"], str, str]] = []
    bodies: list[list[str]] = []
    for line in text.split("\n"):
        found = _HEADER.match(line) if line.startswith(MARK) else None
        if found is not None:
            kind: Literal["rec", "art"] = "rec" if found.group(1) == "REC" else "art"
            heads.append((kind, found.group(2), found.group(3)))
            bodies.append([])
        elif bodies:
            bodies[-1].append(line)
    return [
        Block(kind, number, title, "\n".join(body))
        for (kind, number, title), body in zip(heads, bodies, strict=True)
    ]
