"""EUR-Lex parser budgets and shapes found in review: siblings, footnotes, nesting (T2.4)."""

import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from pruefstand.core.enums import Lang
from pruefstand.ingest.eurlex import EurLexLoader
from pruefstand.ingest.eurlex_blocks import clean, parse_blocks
from pruefstand.ingest.eurlex_parse import EurLexLimits, EurLexParseError, parse_act

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "eurlex"
CELEX = "32016R0679"


def gdpr(lang: str) -> bytes:
    return (FIXTURES / f"gdpr_{lang}.html").read_bytes()


def raw_with(tmp_path: Path, de: bytes, en: bytes) -> Path:
    target = tmp_path / "raw" / CELEX
    target.mkdir(parents=True)
    (target / "de.html").write_bytes(de)
    (target / "en.html").write_bytes(en)
    return tmp_path / "raw"


def best_of(fn: Callable[[], object], runs: int = 3) -> float:
    times = []
    for _ in range(runs):
        start = time.perf_counter()
        fn()
        times.append(time.perf_counter() - start)
    return min(times)


def assert_linear(make: Callable[[int], Callable[[], object]], n: int) -> None:
    small, large = make(n), make(4 * n)
    ratio = best_of(large) / max(best_of(small), 1e-6)
    assert ratio <= 8, f"4x input took {ratio:.1f}x the time"


def sibling_headings_page(n: int) -> bytes:
    """``n`` Article headings as siblings inside one ELI Article div (B1 repro shape)."""
    body = '<p class="oj-ti-art">Article 1</p><p>x</p>' * n
    return f'<html><body><div id="art_1">{body}</div></body></html>'.encode()


def test_parsing_is_linear_for_sibling_headings_in_one_article_div() -> None:
    def make(n: int) -> Callable[[], object]:
        page = sibling_headings_page(n)
        return lambda: parse_act(page)

    assert_linear(make, 400)


def test_each_sibling_heading_stops_at_the_next_one() -> None:
    page = (
        b'<html><body><div id="art_1"><p class="oj-ti-art">Article 1</p><p>one</p>'
        b'<p class="oj-ti-art">Article 2</p><p>two</p></div></body></html>'
    )
    bodies = {b.number: b.body for b in parse_act(page).blocks}
    assert bodies == {"1": "one", "2": "two"}


def footnote_page(n: int) -> bytes:
    refs = '<a><span class="oj-super oj-note-tag">1</span></a>x' * n
    return (
        '<html><body><div id="art_1"><p class="oj-ti-art">Article 1</p>'
        f"<p>{refs}</p></div></body></html>"
    ).encode()


def test_footnote_reference_removal_is_linear() -> None:
    def make(n: int) -> Callable[[], object]:
        page = footnote_page(n)
        return lambda: parse_act(page)

    assert_linear(make, 15_000)


def test_footnote_references_are_removed_and_text_kept() -> None:
    (art,) = parse_act(footnote_page(3)).blocks
    assert art.body == "xxx"


def nested_recitals_page(depth: int) -> bytes:
    opens = "".join(f'<div id="rct_{i}"><p>({i}) Text {i}.</p>' for i in range(1, depth + 1))
    return (
        f"<html><body>{opens}{'</div>' * depth}"
        '<div id="art_1"><p class="oj-ti-art">Article 1</p><p>t</p></div></body></html>'
    ).encode()


def test_nested_recitals_take_only_their_own_text() -> None:
    page = nested_recitals_page(189)
    blocks = parse_act(page).blocks
    recitals = [b for b in blocks if b.kind == "rec"]
    assert len(recitals) == 189
    assert all(b.body == f"({b.number}) Text {b.number}." for b in recitals)
    assert sum(len(b.body) for b in blocks) <= len(page)


def test_text_budget_is_enforced() -> None:
    page = sibling_headings_page(50)
    with pytest.raises(EurLexParseError, match="text"):
        parse_act(page, EurLexLimits(max_chars=20))
    assert parse_act(page, EurLexLimits(max_chars=10_000)).blocks


def test_clean_removes_control_characters() -> None:
    assert clean("a\x00b\x7fc\x85d\x1ee") == "a b c d e"


def test_literal_record_separator_in_source_text_is_not_a_marker(tmp_path: Path) -> None:
    forged = gdpr("en").replace(b"Lawfulness of processing", b"Lawfulness\x1eART 99\tevil")
    docs = {d.lang: d for d in EurLexLoader().load(raw_with(tmp_path, gdpr("de"), forged))}
    en = docs[Lang.EN]
    assert [b.number for b in parse_blocks(en.text) if b.kind == "art"] == ["5", "6"]
    assert en.text.count("\x1e") == len(parse_blocks(en.text))


@pytest.mark.parametrize("ref", [b"&#127;", b"&#133;", b"&#1;"])
def test_control_character_references_are_removed(tmp_path: Path, ref: bytes) -> None:
    page = gdpr("en").replace(b"Lawfulness of processing", b"Lawfulness" + ref + b"ART 99")
    docs = {d.lang: d for d in EurLexLoader().load(raw_with(tmp_path, gdpr("de"), page))}
    assert "\x7f" not in docs[Lang.EN].text
    assert "\x01" not in docs[Lang.EN].text


def test_only_ascii_digits_make_an_article_number() -> None:
    page = (
        '<html><body><div id="art_1"><p class="oj-ti-art">Article \u0663</p>'
        "<p>x</p></div></body></html>"
    ).encode()
    with pytest.raises(EurLexParseError, match="Article"):
        parse_act(page)


ART = '<div id="art_1"><p class="oj-ti-art">Article 1</p><p>a</p></div>'
LOREM = "lorem ipsum dolor " * 11_000


def total_chars(page: bytes) -> int:
    """Output size, or 0 when the budget refuses the file (it must never expand it)."""
    try:
        return sum(len(b.body) + len(b.title) for b in parse_act(page).blocks)
    except EurLexParseError as err:
        if err.kind != "too_much_text":
            raise
        return 0


@pytest.mark.parametrize("kind", ["li", "table", "art-li"])
def test_nested_blocks_in_lists_and_tables_do_not_multiply_the_output(kind: str) -> None:
    n = 40
    if kind == "li":
        opens = "".join(f'<div id="rct_{i + 1}"><ul><li>' for i in range(n))
        closes = "</li></ul></div>" * n
    elif kind == "table":
        opens = "".join(f'<div id="rct_{i + 1}"><table><tr><td>' for i in range(n))
        closes = "</td></tr></table></div>" * n
    else:
        opens = "".join(f'<div id="art_{i + 2}"><ul><li>' for i in range(n))
        closes = "</li></ul></div>" * n
    page = f"<html><body>{ART}{opens}<p>{LOREM}</p>{closes}</body></html>".encode()
    assert total_chars(page) <= len(page)


def test_nested_tables_are_bounded_by_the_budget() -> None:
    n = 60
    opens = "<table><tr><td>" * n
    closes = "</td></tr></table>" * n
    page = f'<html><body>{ART}<div id="rct_1">{opens}{LOREM}{closes}</div></body></html>'.encode()
    start = time.perf_counter()
    assert total_chars(page) <= len(page)
    assert time.perf_counter() - start < 10


def test_flat_recital_scan_is_linear_for_nested_tables() -> None:
    def make(n: int) -> Callable[[], object]:
        opens = "<table><tr><td>" * n
        closes = "</td></tr></table>" * n
        page = (
            f"<html><body>{opens}(1) text{closes}"
            '<p class="ti-art">Article 1</p><p>a</p></body></html>'
        ).encode()

        def run() -> object:
            try:
                return parse_act(page)
            except EurLexParseError:
                return None

        return run

    assert_linear(make, 20)


NESTED_STRONG = """
import resource, sys, time
from pruefstand.ingest.eurlex_parse import parse_act
page = (
    '<html><body><div id="art_1"><p class="oj-ti-art">Article 1</p><p>x</p></div>'
    + '<strong>' * 190 + 'lorem ipsum dolor ' * 216000 + '</strong>' * 190 + '</body></html>'
).encode()
rss = lambda: resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
before = rss()  # a forked child starts from the parent peak, so only the growth counts
start = time.perf_counter()
act = parse_act(page)
print(round(time.perf_counter() - start, 2), rss() - before)
"""


def test_nested_strong_title_is_bounded_in_time_and_memory() -> None:
    out = subprocess.run(  # noqa: S603 - fixed argv, code is a constant of this file
        [sys.executable, "-I", "-c", NESTED_STRONG], capture_output=True, text=True, check=True
    )
    seconds, max_rss_kb = (float(x) for x in out.stdout.split())
    assert seconds < 5
    assert max_rss_kb < 300_000  # the unbounded version grew by about 700 MB
