"""Text extraction from the lxml tree of an EUR-Lex file, with a character budget (T2.4)."""

import re

from lxml import html

from pruefstand.ingest.eurlex_blocks import clean
from pruefstand.ingest.eurlex_errors import TOO_MUCH_TEXT, EurLexParseError

ELI_ARTICLE = re.compile(r"art_[0-9A-Za-z]+\Z")
ELI_RECITAL = re.compile(r"rct_([0-9]{1,4})\Z")


def element_text(el: html.HtmlElement) -> str:
    """Return the cleaned text content of an element."""
    return clean(el.text_content())


class Budget:
    """Characters of extracted text still allowed for one act."""

    def __init__(self, left: int) -> None:
        self.left = left

    def charge(self, lines: list[str]) -> None:
        """Subtract the length of ``lines``; raise when the budget is used up."""
        self.left -= sum(len(line) for line in lines)
        if self.left < 0:
            raise EurLexParseError(TOO_MUCH_TEXT, "extracted text exceeds the limit")


def rows(table: html.HtmlElement) -> list[str]:
    """Return one line per table row: the cell texts joined by spaces (empty rows dropped)."""
    lines = []
    for row in table.xpath("./tr | ./tbody/tr | ./thead/tr"):
        cells = (element_text(c) for c in row if c.tag in ("td", "th"))
        if line := " ".join(c for c in cells if c):
            lines.append(line)
    return lines


def block_lines(el: html.HtmlElement, budget: Budget) -> list[str]:
    """Return the text lines of an element: one per paragraph, list item or table row.

    Nested Article and recital divs are skipped: each has its own block, so a hostile file that
    nests them cannot multiply the output. Every line is charged to ``budget``.
    """
    out: list[str] = []
    collect(el, out, budget)
    return out


def collect(el: html.HtmlElement, out: list[str], budget: Budget) -> None:
    """Append the text lines of ``el`` to ``out`` (recursion depth is bounded by the depth cap)."""
    if not isinstance(el.tag, str):
        return
    if el.tag == "table":
        emit(rows(el), out, budget)
    elif el.tag in ("p", "li", "h1", "h2", "h3", "h4", "h5", "h6"):
        emit([element_text(el)], out, budget)
    else:
        emit([clean(el.text or "")], out, budget)
        for child in el:
            if not is_own_block(child):
                collect(child, out, budget)
            emit([clean(child.tail or "")], out, budget)


def emit(lines: list[str], out: list[str], budget: Budget) -> None:
    """Charge the non-empty ``lines`` to the budget and append them to ``out``."""
    kept = [line for line in lines if line]
    budget.charge(kept)
    out.extend(kept)


def is_own_block(el: html.HtmlElement) -> bool:
    """Whether ``el`` is an Article or recital div, which is extracted as its own block."""
    ident = el.get("id") or ""
    return el.tag == "div" and bool(ELI_ARTICLE.fullmatch(ident) or ELI_RECITAL.fullmatch(ident))
