"""Hardened parsing of one EUR-Lex HTML rendition into recital and Article blocks (T2.4).

The files come from a remote site and are treated as hostile. Defences, in order: a size cap
checked before parsing, strict UTF-8, an lxml HTML parser that opens no network connection, loads
no DTD and resolves no entity (the HTML parser ignores internal subsets, so ``&a;`` stays literal),
a cap on element count and nesting depth, and a text extraction that is one pass over the tree
(no regex with nested quantifiers, no per-element ancestor walk). Control characters are removed
from all text (:func:`~pruefstand.ingest.eurlex_blocks.clean`).

Three layouts are read, found by structure and never by language:

* ``eli``: ``<div id="art_6">`` holding ``<p class="oj-ti-art">`` and ``<div class="eli-title">``,
  recitals as ``<div id="rct_N">`` (all current files);
* ``flat``: the same classes (with or without the ``oj-`` prefix) as siblings without those divs;
  recitals are the tables before the first Article that start with ``(N)``;
* ``legacy``: plain ``<p>`` lines (:mod:`pruefstand.ingest.eurlex_legacy`).

A heading that starts with a quotation mark (``‘Article 8a``) is part of an amending act quoted
inside an Article and is not an Article of its own. Footnote references are dropped.
"""

import re
from dataclasses import dataclass
from datetime import date

from lxml import etree, html

from pruefstand.ingest.eurlex_blocks import Block
from pruefstand.ingest.eurlex_errors import (
    INVALID_ENCODING,
    INVALID_HTML,
    NO_ARTICLES,
    TOO_DEEP,
    TOO_LARGE,
    TOO_MANY_ELEMENTS,
    EurLexParseError,
)
from pruefstand.ingest.eurlex_legacy import ARTICLE, parse_legacy_lines
from pruefstand.ingest.eurlex_meta import act_title, published_date
from pruefstand.ingest.eurlex_text import (
    ELI_ARTICLE,
    ELI_RECITAL,
    Budget,
    block_lines,
    element_text,
    rows,
)

_MIB = 1024 * 1024
_RECITAL_CELL = re.compile(r"\(([0-9]{1,4})\)\Z")
_TITLE_CLASSES = frozenset({"eli-title", "sti-art"})
_STOP_CLASSES = frozenset(
    {"ti-section-1", "ti-section-2", "ti-grseq-1", "doc-end", "final", "signatory"}
)


@dataclass(frozen=True)
class EurLexLimits:
    """Safety limits for one file.

    Attributes:
        max_bytes: File size (the largest pinned file, the German AI Act, is 1.3 MB).
        max_depth: Deepest element nesting (real files stay below 20; libxml2 stops at 256).
        max_elements: Elements of the whole file (the largest real file has about 30 000).
        max_chars: Characters of extracted text per act (the largest real act has about 1.1 M).
    """

    max_bytes: int = 4 * _MIB
    max_depth: int = 200
    max_elements: int = 400_000
    max_chars: int = 8_000_000


@dataclass(frozen=True)
class ParsedAct:
    """One act in one language.

    Attributes:
        title: Title of the act as printed (empty when absent).
        published: Publication date in the Official Journal, when the file states it.
        layout: ``eli``, ``flat`` or ``legacy``.
        blocks: Recitals first, then Articles, in document order.
        duplicates: Block ids that occurred more than once (only the first is kept).
    """

    title: str
    published: date | None
    layout: str
    blocks: tuple[Block, ...]
    duplicates: tuple[str, ...] = ()


def _classes(el: html.HtmlElement) -> frozenset[str]:
    return frozenset(c.removeprefix("oj-") for c in (el.get("class") or "").split())


def _tree(data: bytes, limits: EurLexLimits) -> html.HtmlElement:
    if len(data) > limits.max_bytes:
        raise EurLexParseError(TOO_LARGE, f"{len(data)} bytes exceed {limits.max_bytes}")
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as err:
        raise EurLexParseError(INVALID_ENCODING, str(err)) from err
    parser = html.HTMLParser(
        encoding="utf-8", no_network=True, remove_comments=True, remove_pis=True, huge_tree=False
    )
    try:
        root = html.document_fromstring(data, parser=parser)
    except (etree.ParserError, etree.XMLSyntaxError, ValueError) as err:
        raise EurLexParseError(INVALID_HTML, str(err)) from err
    _check_shape(root, limits)
    return root


def _check_shape(root: html.HtmlElement, limits: EurLexLimits) -> None:
    depth = elements = 0
    for event, _ in etree.iterwalk(root, events=("start", "end")):
        if event == "end":
            depth -= 1
            continue
        depth += 1
        elements += 1
        if depth > limits.max_depth:
            raise EurLexParseError(TOO_DEEP, f"nesting depth above {limits.max_depth}")
        if elements > limits.max_elements:
            raise EurLexParseError(TOO_MANY_ELEMENTS, f"more than {limits.max_elements} elements")


def _strip_noise(root: html.HtmlElement) -> None:
    etree.strip_elements(root, "script", "style", "noscript", with_tail=False)
    # ``clear`` empties the reference in place and keeps its tail: linear, unlike ``drop_tree``,
    # which merges the tail into the previous text node (quadratic for many references).
    for ref in root.xpath('//a[.//span[contains(@class, "note-tag")]]'):
        ref.clear(keep_tail=True)


def _heading_number(p: html.HtmlElement) -> str | None:
    found = ARTICLE.fullmatch(element_text(p))
    return found.group(1).lower() if found else None


def _parent_id(el: html.HtmlElement) -> str:
    parent = el.getparent()
    return (parent.get("id") or "") if parent is not None else ""


def _headings(root: html.HtmlElement) -> tuple[list[html.HtmlElement], bool]:
    """Return the Article headings in order and whether the file uses the ELI divs."""
    found = [p for p in root.iter("p") if "ti-art" in _classes(p) and _heading_number(p)]
    eli = [p for p in found if ELI_ARTICLE.fullmatch(_parent_id(p))]
    return (eli, True) if eli else (found, False)


def _is_stop(sibling: html.HtmlElement, *, eli: bool) -> bool:
    """Whether ``sibling`` ends the Article above it.

    The next Article heading always does; in the flat layout so does a chapter or section heading.
    """
    classes = _classes(sibling)
    if "ti-art" in classes and _heading_number(sibling) is not None:
        return True
    return not eli and bool(classes & _STOP_CLASSES)


def _article(heading: html.HtmlElement, number: str, *, eli: bool, budget: Budget) -> Block:
    title = ""
    lines: list[str] = []
    for sibling in heading.itersiblings():
        if _is_stop(sibling, eli=eli):
            break
        if not title and _classes(sibling) & _TITLE_CLASSES:
            title = element_text(sibling)
        else:
            lines.extend(block_lines(sibling, budget))
    return Block("art", number, title, "\n".join(lines))


def _eli_recitals(root: html.HtmlElement, budget: Budget) -> list[Block]:
    blocks = []
    for div in root.iter("div"):
        found = ELI_RECITAL.fullmatch(div.get("id") or "")
        if found and (lines := block_lines(div, budget)):
            blocks.append(Block("rec", found.group(1), "", "\n".join(lines)))
    return blocks


def _flat_recitals(root: html.HtmlElement, first: html.HtmlElement) -> list[Block]:
    blocks: list[Block] = []
    for el in root.iter("table", "p"):
        if el is first:
            break
        lines = rows(el) if el.tag == "table" else []
        cell = lines[0].split(" ", 1)[0] if lines else ""
        found = _RECITAL_CELL.fullmatch(cell)
        if found and int(found.group(1)) == len(blocks) + 1:
            blocks.append(Block("rec", found.group(1), "", "\n".join(lines)))
    return blocks


def _unique(blocks: list[Block]) -> tuple[tuple[Block, ...], tuple[str, ...]]:
    seen: set[str] = set()
    kept: list[Block] = []
    duplicates: list[str] = []
    for block in blocks:
        if block.block_id in seen:
            duplicates.append(block.block_id)
        else:
            seen.add(block.block_id)
            kept.append(block)
    return tuple(kept), tuple(duplicates)


def _legacy_lines(root: html.HtmlElement) -> list[str]:
    paragraphs = root.xpath("//p[not(.//p)]")
    return [line for p in paragraphs if (line := element_text(p))]


def parse_act(data: bytes, limits: EurLexLimits | None = None) -> ParsedAct:
    """Parse one rendition (see the module docstring).

    Args:
        data: The raw bytes of ``de.html`` or ``en.html``.
        limits: Safety limits (default :class:`EurLexLimits`).

    Returns:
        The title, publication date, layout and blocks.

    Raises:
        EurLexParseError: The file is too large, not UTF-8, not parseable, too deep or too
            wide, has too much text, or holds no Article.
    """
    limits = limits or EurLexLimits()
    budget = Budget(limits.max_chars)
    root = _tree(data, limits)
    _strip_noise(root)
    headings, eli = _headings(root)
    if headings:
        numbers = [_heading_number(h) or "" for h in headings]
        articles = [
            _article(h, n, eli=eli, budget=budget) for h, n in zip(headings, numbers, strict=True)
        ]
        recitals = _eli_recitals(root, budget) if eli else _flat_recitals(root, headings[0])
        layout, blocks = ("eli" if eli else "flat"), recitals + articles
    else:
        layout, blocks = "legacy", parse_legacy_lines(_legacy_lines(root))
    kept, duplicates = _unique(blocks)
    if not any(b.kind == "art" for b in kept):
        raise EurLexParseError(NO_ARTICLES, "no Article heading found")
    return ParsedAct(act_title(root), published_date(root), layout, kept, duplicates)
