"""Hardened parsing of the untrusted GII XML.

The GII files are served by a remote site, so they are treated as hostile. Defences, in order:

* size, encoding and declaration checks on the raw bytes: no ``<!ENTITY``, no internal DTD
  subset (the real files only *reference* ``gii-norm.dtd`` and never declare anything), only
  UTF-8 or ASCII;
* an lxml parser that resolves no entities, loads no DTD, never opens the network and has no
  ``huge_tree`` mode (so libxml2's own depth and node-size limits stay on);
* our own limits on nesting depth and norm count while streaming with ``iterparse``.

The result is an iterator of ``<norm>`` elements; each is cleared after the consumer is done,
so memory stays flat for the biggest law.
"""

import io
import re
from collections.abc import Iterator
from dataclasses import dataclass

from lxml import etree

from pruefstand.ingest.gii.errors import GiiParseError, UnsafeXmlError

_MIB = 1024 * 1024
_HEAD_BYTES = 4096
_INTERNAL_SUBSET = re.compile(rb"<!DOCTYPE[^>\[]*\[")
_ENCODING = re.compile(rb"<\?xml[^>]*?encoding\s*=\s*[\"']([^\"']+)[\"']")
_ALLOWED_ENCODINGS = frozenset({"utf-8", "utf8", "us-ascii", "ascii"})
_BOMS = (b"\xff\xfe", b"\xfe\xff", b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")


@dataclass(frozen=True)
class XmlLimits:
    """Safety limits for one XML document.

    Attributes:
        max_bytes: Size of the document in bytes.
        max_depth: Deepest element nesting (real GII files stay below 25).
        max_norms: Number of ``<norm>`` elements (the largest law has about 3 000).
    """

    max_bytes: int = 64 * _MIB
    max_depth: int = 100
    max_norms: int = 100_000


def hardened_parser() -> etree.XMLParser:
    """Return an lxml parser that cannot read files, open sockets or expand entities.

    Returns:
        A parser with ``resolve_entities=False``, ``no_network=True``, ``load_dtd=False``,
        ``huge_tree=False``; comments and processing instructions are dropped.
    """
    return etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        dtd_validation=False,
        attribute_defaults=False,
        huge_tree=False,
        remove_comments=True,
        remove_pis=True,
        collect_ids=False,
    )


def _check_bytes(data: bytes, limits: XmlLimits) -> None:
    if len(data) > limits.max_bytes:
        msg = f"xml size {len(data)} exceeds the limit of {limits.max_bytes} bytes"
        raise UnsafeXmlError(msg)
    head = data[:_HEAD_BYTES]
    declared = _ENCODING.search(head)
    if head.startswith(_BOMS) or b"\x00" in head:
        msg = "xml encoding is not UTF-8"
        raise UnsafeXmlError(msg)
    if declared is not None and declared.group(1).decode("ascii", "replace").lower() not in (
        _ALLOWED_ENCODINGS
    ):
        msg = "xml encoding is not UTF-8"
        raise UnsafeXmlError(msg)
    if _INTERNAL_SUBSET.search(head) or b"<!ENTITY" in data:
        msg = "xml declares entities or an internal DTD subset"
        raise UnsafeXmlError(msg)


def _iterparse(data: bytes) -> "etree.iterparse[tuple[str, etree._Element]]":
    return etree.iterparse(
        io.BytesIO(data),
        events=("start", "end"),
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        dtd_validation=False,
        attribute_defaults=False,
        huge_tree=False,
        remove_comments=True,
        remove_pis=True,
    )


def _release(norm: etree._Element) -> None:
    """Free a processed norm and every sibling before it."""
    parent = norm.getparent()
    norm.clear()
    while parent is not None and norm.getprevious() is not None:
        del parent[0]


def iter_norms(data: bytes, limits: XmlLimits | None = None) -> Iterator[etree._Element]:
    """Yield every ``<norm>`` element of a GII document, in document order.

    The element is only valid until the next one is requested (it is cleared afterwards).

    Args:
        data: The raw XML bytes.
        limits: Safety limits (defaults: :class:`XmlLimits`).

    Yields:
        ``<norm>`` elements; ``norm.getparent().get("builddate")`` is the document build date.

    Raises:
        UnsafeXmlError: The document breaks a safety rule or limit.
        GiiParseError: The document is not well-formed.
    """
    limits = limits or XmlLimits()
    _check_bytes(data, limits)
    depth = 0
    count = 0
    try:
        for event, elem in _iterparse(data):
            if event == "start":
                depth += 1
                if depth > limits.max_depth:
                    msg = f"xml nesting depth exceeds {limits.max_depth}"
                    raise UnsafeXmlError(msg)
                continue
            depth -= 1
            if elem.tag == "norm":
                count += 1
                if count > limits.max_norms:
                    msg = f"xml holds more than {limits.max_norms} norms"
                    raise UnsafeXmlError(msg)
                yield elem
                _release(elem)
    except etree.XMLSyntaxError as err:
        if "depth" in str(err).lower():
            msg = "xml nesting depth exceeds the parser limit"
            raise UnsafeXmlError(msg) from err
        msg = f"invalid xml: {err}"
        raise GiiParseError(msg) from err
