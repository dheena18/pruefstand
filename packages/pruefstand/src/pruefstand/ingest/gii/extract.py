"""Turn the content of a GII ``<norm>`` into plain text.

Conventions (all structure the chunker and the readers rely on):

* each ``<P>`` is its own line, so an Absatz stays ``(1) ...`` at the start of a line;
* ``<DL>`` lists become one line per item, ``<DT>`` and ``<DD>`` joined by a space
  (``1. zwei Jahre ...``);
* tables become one line per row, cells joined by `` | ``;
* footnotes, footnote references, images, files and ``<kommentar>`` notes are dropped,
  ``<BR/>`` is a line break;
* everything else (``<B>``, ``<I>``, ``<SUB>``, ``<LA>``, ...) contributes only its text;
* the result is NFC with whitespace collapsed per line
  (:func:`pruefstand.ingest.text.normalise_text`).

Recursion depth is bounded by the nesting limit of :mod:`pruefstand.ingest.gii.xmlparse`.
"""

from lxml import etree

from pruefstand.ingest.text import normalise_line, normalise_text

_DROP = frozenset({"FnR", "FnArea", "Footnote", "Footnotes", "fussnoten", "F", "IMG", "FILE",
                   "kommentar", "Split"})  # fmt: skip
_BLOCK = frozenset({"P", "Content", "TOC", "Title", "Ident"})


def _flat(text: str | None) -> str:
    """Source line breaks are XML whitespace; only ``<BR/>`` and block elements break lines."""
    return (text or "").replace("\r", " ").replace("\n", " ")


def _children(elem: etree._Element, out: list[str]) -> None:
    out.append(_flat(elem.text))
    for child in elem:
        _walk(child, out)
        out.append(_flat(child.tail))


def _walk(elem: etree._Element, out: list[str]) -> None:
    tag = elem.tag
    if not isinstance(tag, str) or tag in _DROP:
        return
    if tag == "BR":
        out.append("\n")
    elif tag == "table":
        _table(elem, out)
    elif tag == "DL":
        _list(elem, out)
    elif tag in _BLOCK:
        out.append("\n")
        _children(elem, out)
        out.append("\n")
    else:
        _children(elem, out)


def _inline(elem: etree._Element) -> str:
    out: list[str] = []
    _children(elem, out)
    return "".join(out)


def _list(dl: etree._Element, out: list[str]) -> None:
    out.append("\n")
    out.append(_flat(dl.text))
    for child in dl:
        if child.tag == "DT":
            out.append("\n" + _inline(child) + " ")
        elif child.tag == "DD":
            out.append(_inline(child) + "\n")
        else:
            _walk(child, out)
        out.append(_flat(child.tail))
    out.append("\n")


def _table(table: etree._Element, out: list[str]) -> None:
    for row in table.iterfind("tgroup/*/row"):
        cells = [normalise_line(_inline(entry)) for entry in row.iterfind("entry")]
        while cells and not cells[-1]:
            cells.pop()
        if cells:
            out.append("\n" + " | ".join(cells) + "\n")


def norm_text(norm: etree._Element) -> str:
    """Return the normative text of a ``<norm>`` (empty when it has none).

    Args:
        norm: A ``<norm>`` element.

    Returns:
        NFC text, one line per paragraph, list item or table row; ``""`` if there is no text.
    """
    text = norm.find("textdaten/text")
    if text is None:
        return ""
    out: list[str] = []
    _children(text, out)
    return normalise_text("".join(out))
