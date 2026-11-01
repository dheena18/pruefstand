"""Text extraction from the lxml tree of an EUR-Lex file, with a character budget (T2.4).

Every piece of text that is built is charged to a :class:`Budget`, so the work and the memory
of a hostile file (nested tables, nested Article or recital divs inside ``<li>`` or ``<table>``)
are bounded by the budget, which the parser sets from the size of the input. Article and recital
divs are extracted as blocks of their own, so their text is left out of every enclosing element.
"""

import re

from lxml import html

from pruefstand.ingest.eurlex_blocks import clean
from pruefstand.ingest.eurlex_errors import TOO_MUCH_TEXT, EurLexParseError

ELI_ARTICLE = re.compile(r"art_[0-9A-Za-z]+\Z")
ELI_RECITAL = re.compile(r"rct_([0-9]{1,4})\Z")
_TEXT_TAGS = frozenset({"p", "li", "h1", "h2", "h3", "h4", "h5", "h6"})


class Budget:
    """Characters of extracted text still allowed for one act."""

    def __init__(self, left: int) -> None:
        self.left = left

    def charge(self, size: int) -> None:
        """Subtract ``size``; raise when the budget is used up."""
        self.left -= size
        if self.left < 0:
            raise EurLexParseError(TOO_MUCH_TEXT, "extracted text exceeds the limit")


def is_own_block(el: html.HtmlElement) -> bool:
    """Whether ``el`` is an Article or recital div, which is extracted as its own block."""
    ident = el.get("id") or ""
    return el.tag == "div" and bool(ELI_ARTICLE.fullmatch(ident) or ELI_RECITAL.fullmatch(ident))


def element_text(el: html.HtmlElement, budget: Budget | None = None) -> str:
    """Return the cleaned text of ``el`` without the text of own-block descendants.

    One iterative pass (no recursion, no ``text_content`` of subtrees); the pieces are charged
    to ``budget`` as they are collected.
    """
    parts: list[str] = []
    stack: list[html.HtmlElement | str] = [el]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            parts.append(item)
            continue
        if not isinstance(item.tag, str):
            continue
        items: list[html.HtmlElement | str] = [item.text or ""]
        for child in item:
            if not is_own_block(child):
                items.append(child)
            items.append(child.tail or "")
        for piece in reversed(items):
            if isinstance(piece, str):
                if piece and budget is not None:
                    budget.charge(len(piece))
                if piece:
                    stack.append(piece)
            else:
                stack.append(piece)
    return clean("".join(parts))


def rows(table: html.HtmlElement, budget: Budget | None = None) -> list[str]:
    """Return one line per table row: the cell texts joined by spaces (empty rows dropped)."""
    lines = []
    for row in table.xpath("./tr | ./tbody/tr | ./thead/tr"):
        cells = (element_text(c, budget) for c in row if c.tag in ("td", "th"))
        if line := " ".join(c for c in cells if c):
            lines.append(line)
    return lines


def block_lines(el: html.HtmlElement, budget: Budget) -> list[str]:
    """Return the text lines of an element: one per paragraph, list item or table row.

    Nested Article and recital divs are skipped, so a hostile file that nests them cannot
    multiply the output. Every piece of text is charged to ``budget``.
    """
    out: list[str] = []
    collect(el, out, budget)
    return out


def collect(el: html.HtmlElement, out: list[str], budget: Budget) -> None:
    """Append the text lines of ``el`` to ``out`` (recursion depth is bounded by the depth cap)."""
    if not isinstance(el.tag, str):
        return
    if el.tag == "table":
        out.extend(rows(el, budget))
    elif el.tag in _TEXT_TAGS:
        out.extend(filter(None, [element_text(el, budget)]))
    else:
        _piece(el.text, out, budget)
        for child in el:
            if not is_own_block(child):
                collect(child, out, budget)
            _piece(child.tail, out, budget)


def _piece(text: str | None, out: list[str], budget: Budget) -> None:
    if text:
        budget.charge(len(text))
        if line := clean(text):
            out.append(line)
