"""Minimal EUR-Lex XHTML reader: pulls single articles out of a CELLAR rendition (T1.13 S1).

Only what the slice needs (DSGVO Art. 5 and 6 in German and English). T2.4 replaces it with the
full EUR-Lex loader. The input is the official XHTML stored by ``data/download.py`` as
``raw/eurlex/<celex>/{de,en}.html``; articles are ``<div id="art_<n>">`` with a title block
(``art_<n>.tit_1``), numbered paragraphs as child ``<div>`` and lettered points as table rows.
"""

import re
import unicodedata
from collections.abc import Collection
from dataclasses import dataclass

from lxml import etree, html

_SPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class Article:
    """One article: number, title and text (one line per numbered paragraph or lettered point)."""

    number: int
    title: str
    text: str


def _norm(text: str) -> str:
    return _SPACE.sub(" ", unicodedata.normalize("NFC", text)).strip()


def _lines(node: etree._Element) -> list[str]:
    out: list[str] = []
    for child in node:
        tag = child.tag if isinstance(child.tag, str) else ""
        if tag == "p":
            if line := _norm("".join(child.itertext())):
                out.append(line)
        elif tag == "table":
            for row in child.iter("tr"):
                cells = [_norm("".join(td.itertext())) for td in row.findall("td")]
                if line := " ".join(c for c in cells if c):
                    out.append(line)
        elif tag == "div":
            out.extend(_lines(child))
    return out


def _article(root: etree._Element, number: int) -> Article | None:
    nodes = root.xpath(f'//div[@id="art_{number}"]')
    if not nodes:
        return None
    node = nodes[0]
    title = ""
    body: list[str] = []
    for child in node:
        if child.tag == "div" and "eli-title" in (child.get("class") or "").split():
            title = _norm("".join(child.itertext()))
        elif child.tag == "div":
            body.extend(_lines(child))
    return Article(number=number, title=title, text="\n".join(body))


def parse_articles(document: str | bytes, numbers: Collection[int]) -> list[Article]:
    """Extract the requested articles from an EUR-Lex XHTML document.

    Args:
        document: The XHTML of the act (bytes when it carries an encoding declaration).
        numbers: Article numbers to extract.

    Returns:
        The articles that exist, in ascending number order.

    Examples:
        >>> doc = (
        ...     '<div id="art_1"><div class="eli-title"><p>Titel</p></div>'
        ...     '<div><p>(1) Text</p></div></div>'
        ... )
        >>> parse_articles(doc, {1})
        [Article(number=1, title='Titel', text='(1) Text')]
    """
    root = html.fromstring(document)
    found = (_article(root, n) for n in sorted(numbers))
    return [a for a in found if a is not None]
