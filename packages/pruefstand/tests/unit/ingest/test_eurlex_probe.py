"""EUR-Lex heading probe budget and pinned parser budgets (T2.4a)."""

import pytest

from pruefstand.ingest import eurlex_text
from pruefstand.ingest.eurlex_blocks import clean
from pruefstand.ingest.eurlex_errors import TOO_MUCH_TEXT, EurLexParseError
from pruefstand.ingest.eurlex_parse import parse_act

ART = '<div id="art_1"><p class="oj-ti-art">Article 1</p><p>a</p></div>'
DEPTH = 80


def nested_headings_page(depth: int) -> bytes:
    """``depth`` heading paragraphs nested through spans: each would rebuild the inner text."""
    opens = '<p class="oj-ti-art"><span>Article 1' * depth
    return f"<html><body>{ART}{opens}{'</span></p>' * depth}</body></html>".encode()


def test_nested_heading_paragraphs_are_not_headings_and_read_a_bounded_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    read: list[int] = []

    def counting(text: str) -> str:
        read.append(len(text))
        return clean(text)

    monkeypatch.setattr(eurlex_text, "clean", counting)
    blocks = parse_act(nested_headings_page(DEPTH)).blocks
    assert [(b.kind, b.number) for b in blocks] == [("art", "1")]
    # a probe reads at most 64 characters per paragraph; the whole inner text was ~ DEPTH**2 * 5
    assert sum(read) < 100 * DEPTH


def nested_cells(depth: int, text: str) -> str:
    """``depth`` tables, each cell holding the next table; the text is in the innermost."""
    inner = f"<td>{text}</td>"
    for _ in range(depth):
        inner = f"<td><table><tr>{inner}</tr></table></td>"
    return f"<table><tr>{inner}</tr></table>"


def test_small_nested_list_and_table_pages_parse_into_the_expected_blocks() -> None:
    # element_text leaves the text of nested Article/recital divs out of every enclosing element
    # (text_content() would keep it), and joins list items and table rows as lines
    page = (
        b'<html><body><div id="art_1"><p class="oj-ti-art">Article 1</p>'
        b'<ul><li>one<ul><li>two</li></ul><div id="rct_7"><p>(7) recital</p></div></li></ul>'
        b'<table><tr><td>cell a</td><td>cell b<div id="rct_8"><p>(8) rec</p></div></td></tr>'
        b"</table>"
        b"</div></body></html>"
    )
    bodies = {(b.kind, b.number): b.body for b in parse_act(page).blocks}
    assert bodies[("art", "1")] == "onetwo\ncell a cell b"
    assert bodies[("rec", "7")] == "(7) recital"
    assert bodies[("rec", "8")] == "(8) rec"


def nested_flat_articles(depth: int, text: str) -> bytes:
    """Flat layout: every Article heading is followed by the div that holds all later ones."""
    opens = "".join(f'<div><p class="ti-art">Article {n}</p><p>{text}</p>' for n in range(depth))
    return f"<html><body>{opens}{'</div>' * depth}</body></html>".encode()


def test_default_limits_refuse_an_amplifying_page() -> None:
    # every heading's siblings include the div with all later Articles: depth**2 / 2 times the
    # text for a file of depth * size; the size-relative budget (2 * len(data)) refuses it, the
    # fixed 8 M-character cap alone would not (here about 1.6 M characters)
    page = nested_flat_articles(40, "x" * 2000)
    assert len(page) < 100_000
    with pytest.raises(EurLexParseError) as caught:
        parse_act(page)
    assert caught.value.kind == TOO_MUCH_TEXT


def test_nested_tables_inside_a_flat_recital_are_not_rescanned() -> None:
    # `not _in_table(el)`: without it every nested table is a recital candidate and its rows are
    # charged again (depth * size), which the size-relative budget refuses
    big = "y" * 6000
    page = (
        "<html><body><table><tr><td>(1)</td><td>"
        f"{nested_cells(5, big)}</td></tr></table>"
        '<p class="ti-art">Article 1</p><p>a</p></body></html>'
    ).encode()
    kinds = [(b.kind, b.number) for b in parse_act(page).blocks]
    assert kinds == [("rec", "1"), ("art", "1")]
