"""Title and publication date of an EUR-Lex rendition (T2.4)."""

import re
from datetime import date

from lxml import html

from pruefstand.ingest.eurlex_blocks import clean

_DOT_DATE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")
_SLASH_DATE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")
_MAX_TITLE = 500


def act_title(root: html.HtmlElement) -> str:
    """Return the title of the act as printed (up to 500 characters; empty if absent).

    Args:
        root: The parsed document.

    Returns:
        The ``doc-ti`` lines joined by spaces, else the first ``<strong>`` (legacy layout), else
        the ``<title>``.
    """
    parts = [_clean_text(p) for p in root.xpath('//p[contains(@class, "doc-ti")]')][:6]
    if not parts:
        parts = [_clean_text(s) for s in root.xpath("//strong")][:1] or [
            _clean_text(t) for t in root.iter("title")
        ][:1]
    return clean(" ".join(p for p in parts if p))[:_MAX_TITLE]


def published_date(root: html.HtmlElement) -> date | None:
    """Return the Official Journal publication date, or ``None`` when the file has none.

    Args:
        root: The parsed document.

    Returns:
        The date of the ``hd-date`` header (``4.5.2016``) or of the ``DC.source`` meta tag
        (``Official Journal L 299 , 18/11/2003``).
    """
    candidates = [
        (_DOT_DATE, p.text_content()) for p in root.xpath('//p[contains(@class, "hd-date")]')
    ] + [(_SLASH_DATE, m.get("content") or "") for m in root.xpath('//meta[@name="DC.source"]')]
    for pattern, text in candidates:
        if found := pattern.search(text):
            day, month, year = (int(g) for g in found.groups())
            try:
                return date(year, month, day)
            except ValueError:
                continue
    return None


def _clean_text(el: html.HtmlElement) -> str:
    return clean(el.text_content())
