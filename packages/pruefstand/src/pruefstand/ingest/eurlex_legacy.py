"""Plain-text layout of the oldest EUR-Lex renditions (Directives 2002/58/EC and 2003/88/EC) (T2.4).

These files have no CSS classes: the act is a flat run of ``<p>`` lines inside ``div#TexteOnly``.
Recitals are lines ``(N) text`` before the first Article; an Article is a line ``Article N`` /
``Artikel N`` followed by its title and its paragraphs. A chapter heading ends the Article above
it (the heading and the chapter title are dropped); the signature (``Done at ...``) or an
``ANNEX`` / ``ANHANG`` line ends the act: the footnotes and annexes behind it are not read.
One pass over the lines, so the time is linear.
"""

import re
from collections.abc import Sequence

from pruefstand.ingest.eurlex_blocks import Block

ARTICLE = re.compile(r"(?:Article|Artikel)\s+([0-9]{1,4}[A-Za-z]{0,2})\Z")
_CHAPTER = re.compile(
    r"(?:CHAPTER|KAPITEL|SECTION|ABSCHNITT|TITLE|TITEL|PART|TEIL)\s+[IVXLC0-9]+\Z"
)
_END = re.compile(r"(?:Done at|Geschehen zu|Geschehen|Fait à|ANNEX|ANHANG)\b")
_RECITAL = re.compile(r"\(([0-9]{1,3})\)\s+(\S.*)\Z")
_LIST_START = re.compile(r"\(?[0-9]{1,3}[.)]\s|\([a-z]{1,2}\)")
_MAX_TITLE = 200


def _is_recital_end(line: str) -> bool:
    """A line that closes the recitals: an upper-case or colon-terminated formula line."""
    return line.isupper() or line.endswith(":")


def _recitals(lines: Sequence[str]) -> tuple[list[Block], int]:
    """Collect the recitals before the first Article; return them and the index of that line."""
    blocks: list[tuple[int, list[str]]] = []
    open_recital = False
    for index, line in enumerate(lines):
        if ARTICLE.fullmatch(line):
            return _finish(blocks), index
        found = _RECITAL.fullmatch(line)
        if found and int(found.group(1)) == len(blocks) + 1:
            blocks.append((int(found.group(1)), [line]))
            open_recital = True
        elif open_recital and not _is_recital_end(line):
            blocks[-1][1].append(line)
        else:
            open_recital = False
    return _finish(blocks), len(lines)


def _finish(blocks: list[tuple[int, list[str]]]) -> list[Block]:
    return [Block("rec", str(n), "", "\n".join(body)) for n, body in blocks]


def _article(number: str, body: list[str]) -> Block:
    title = ""
    if body and len(body[0]) <= _MAX_TITLE and not _LIST_START.match(body[0]):
        title, body = body[0], body[1:]
    return Block("art", number.lower(), title, "\n".join(body))


def parse_legacy_lines(lines: Sequence[str]) -> list[Block]:
    """Parse the cleaned, non-empty lines of a legacy rendition into recital and Article blocks.

    Args:
        lines: The text lines of the act in order (already passed through ``clean``).

    Returns:
        Recitals first, then Articles; empty when there is no ``Article N`` line.

    Examples:
        >>> blocks = parse_legacy_lines(
        ...     ["Whereas:", "(1) Grund.", "HAVE ADOPTED:", "CHAPTER 1", "Scope",
        ...      "Article 1", "Aim", "1. Text.", "Done at Brussels", "Article 2", "ignored"]
        ... )
        >>> [(b.block_id, b.title, b.body) for b in blocks]
        [('rec-1', '', '(1) Grund.'), ('art-1', 'Aim', '1. Text.')]
    """
    blocks, start = _recitals(lines)
    number: str | None = None
    body: list[str] = []
    for line in lines[start:]:
        found = ARTICLE.fullmatch(line)
        if found or _CHAPTER.fullmatch(line) or _END.match(line):
            if number is not None:
                blocks.append(_article(number, body))
            number, body = (found.group(1) if found else None), []
            if not found and _END.match(line):
                return blocks
        elif number is not None:
            body.append(line)
    if number is not None:
        blocks.append(_article(number, body))
    return blocks
