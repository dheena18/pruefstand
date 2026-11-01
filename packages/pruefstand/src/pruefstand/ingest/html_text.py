"""HTML -> plain text for court decisions (T2.3; reusable for the EUR-Lex HTML of T2.4).

The OLDP ``content`` column is HTML in several dialects (juris ``<dl><dt>`` Randnummern, nested
layout tables, ``<h2>``/``<h4>`` headings, or plain text in a single ``<p>``). The conversion keeps
what the chunkers need: block elements become lines (a heading and a Randnummer stay on a line of
their own), table cells are separated by a space, inline elements do not break words. Newlines
inside text nodes are kept because decisions that have no markup structure carry their headings
as lines of one ``<p>``.

Untrusted input: the parser is lxml's HTML parser without network access and without the ``huge``
option (libxml2 stops at its default nesting limit), comments and processing instructions are
removed, ``script``/``style`` content is dropped, and the tree is walked iteratively, so no input
can exhaust the Python stack. The time is linear in the markup.
"""

from lxml import etree
from lxml import html as lxml_html

from pruefstand.core.errors import PruefstandError
from pruefstand.ingest.text import join_hyphenation, normalise_text

_BLOCK = frozenset(
    {
        "address", "article", "aside", "blockquote", "body", "br", "caption", "center", "dd",
        "div", "dl", "dt", "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2",
        "h3", "h4", "h5", "h6", "header", "hr", "html", "li", "main", "nav", "ol", "p", "pre",
        "section", "table", "tbody", "tfoot", "thead", "tr", "ul",
    }
)  # fmt: skip
_CELL = frozenset({"td", "th"})
_DROP = ("script", "style", "noscript", "template", "head", "title")
_CONTROL = dict.fromkeys([*range(0, 9), 11, 12, *range(14, 32)])


class HtmlTextError(PruefstandError):
    """The markup cannot be parsed at all (the parser raised)."""


def _parse(markup: str) -> lxml_html.HtmlElement | None:
    parser = lxml_html.HTMLParser(
        remove_comments=True, remove_pis=True, no_network=True, huge_tree=False, recover=True
    )
    try:
        root = lxml_html.document_fromstring(markup, parser=parser)
    except etree.ParserError:
        return None  # "Document is empty": nothing but comments or whitespace
    except (etree.LxmlError, ValueError) as error:
        raise HtmlTextError(f"{type(error).__name__}: {error}"[:200]) from error
    return root


def html_to_text(markup: str) -> str:
    r"""Convert decision HTML to plain text lines.

    Args:
        markup: HTML (or plain text) of one decision.

    Returns:
        NFC text: one line per block element, whitespace runs collapsed, blank lines dropped,
        entities decoded, words hyphenated at a line end joined (``Kündi-`` / ``gung``).

    Raises:
        HtmlTextError: The parser failed outright (it recovers from ordinary broken markup).

    Examples:
        >>> html_to_text("<h2>Tenor</h2><p>Die K&uuml;ndigung ist <b>wirksam</b>.</p>")
        'Tenor\nDie Kündigung ist wirksam.'
    """
    markup = markup.translate(_CONTROL)
    if not markup.strip():
        return ""
    if "<" not in markup and "&" not in markup:
        return join_hyphenation(normalise_text(markup))
    root = _parse(markup)
    if root is None:
        return ""
    etree.strip_elements(root, *_DROP, with_tail=False)  # C loop, keeps the tail text
    parts: list[str] = []
    for event, element in etree.iterwalk(root, events=("start", "end")):
        tag = element.tag if isinstance(element.tag, str) else ""
        if event == "start":
            parts.append("\n" if tag in _BLOCK else " " if tag in _CELL else "")
            parts.append(element.text or "")
        else:
            parts.append("\n" if tag in _BLOCK else "")
            if element is not root:
                parts.append(element.tail or "")
    return join_hyphenation(normalise_text("".join(parts)))
