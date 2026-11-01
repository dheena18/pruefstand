"""html_to_text (T2.3): HTML of the court decisions -> plain text lines, hardened."""

import contextlib
import time
from typing import Any

import pytest
from lxml import html as lxml_html

from pruefstand.ingest.html_text import HtmlTextError, html_to_text


def test_blocks_become_lines_and_inline_tags_do_not_break_words() -> None:
    assert html_to_text("<h2>Tenor</h2><p>Die K<b>ün</b>digung ist <i>wirksam</i>.</p>") == (
        "Tenor\nDie Kündigung ist wirksam."
    )


def test_line_breaks_and_table_cells() -> None:
    assert html_to_text(
        "<p>Zeile eins<br>Zeile zwei</p><table><tr><td>1</td><td>Text</td></tr></table>"
    ) == ("Zeile eins\nZeile zwei\n1 Text")


def test_nested_randnummer_tables_keep_number_and_text_apart() -> None:
    html = (
        "<table><tr><td><table><tr><td>1&#160;</td></tr></table></td>"
        '<td><table><tr><td><rd nr="1"/>Die Beteiligten streiten.</td></tr></table></td>'
        "</tr></table>"
    )
    assert html_to_text(html).split("\n") == ["1", "Die Beteiligten streiten."]


def test_entities_named_numeric_and_nbsp() -> None:
    assert html_to_text(
        "<p>K&uuml;ndigung&#160;&#8211; Gr&#252;&szlig;e&nbsp;&amp;&nbsp;Co</p>"
    ) == ("Kündigung – Grüße & Co")


def test_script_style_comment_and_processing_instructions_are_dropped() -> None:
    html = (
        "<?php echo 1 ?><p>a</p><script>x()</script><style>p{}</style><!-- c -->"
        "<noscript>n</noscript><p>b</p>"
    )
    assert html_to_text(html) == "a\nb"


def test_text_after_a_dropped_element_is_kept() -> None:
    assert html_to_text("<p>vor <script>x()</script>nach</p>") == "vor nach"


def test_plain_text_keeps_its_lines() -> None:
    assert (
        html_to_text("Gründe \n \nDas Gericht entscheidet.  ") == "Gründe\nDas Gericht entscheidet."
    )


def test_a_lone_ampersand_or_angle_bracket_is_text() -> None:
    assert html_to_text("a < b & c > d") == "a < b & c > d"


def test_broken_markup_recovers() -> None:
    assert html_to_text("<p>eins<p>zwei</div></b>") == "eins\nzwei"


def test_hyphenation_at_line_ends_is_joined() -> None:
    assert (
        html_to_text("<p>Arbeits-\nverhältnis und Ost-\nWest</p>")
        == "Arbeitsverhältnis und Ost-\nWest"
    )


@pytest.mark.parametrize("markup", ["", "   ", "<p> </p>", "<!-- nur -->", "<script>x</script>"])
def test_nothing_visible_gives_the_empty_string(markup: str) -> None:
    assert html_to_text(markup) == ""


def test_output_is_nfc() -> None:
    assert html_to_text("<p>Kündigung</p>") == "Kündigung"


def best_of(runs: int, markup: str) -> float:
    best = float("inf")
    for _ in range(runs):
        start = time.perf_counter()
        html_to_text(markup)
        best = min(best, time.perf_counter() - start)
    return best


def test_time_is_linear_in_the_markup() -> None:
    unit = "<div><p>Die <b>Kündigung</b> &uuml;ber § 622 BGB.</p><br></div>"
    small, large = best_of(3, unit * 2_000), best_of(3, unit * 16_000)
    assert large / small < 20  # linear = 8, quadratic = 64


@pytest.mark.parametrize(
    "markup",
    ["<div>" * 100_000, "<" * 500_000, "<p>" * 200_000 + "x", "&" * 500_000, "<a " * 100_000],
)
def test_pathological_markup_terminates_quickly(markup: str) -> None:
    start = time.perf_counter()
    with contextlib.suppress(HtmlTextError):  # the one documented way to refuse
        assert isinstance(html_to_text(markup), str)
    assert time.perf_counter() - start < 10


@pytest.mark.parametrize(
    "unit", ["<script></script>x", "<style>a</style>x", "<script>y</script>x", "<title>t</title>x"]
)
def test_dropped_elements_cost_linear_time(unit: str) -> None:
    small, large = best_of(3, unit * 10_000), best_of(3, unit * 40_000)  # 4x the markup
    assert large / small <= 8  # linear = 4, quadratic = 16


def test_dropped_elements_keep_their_tail_text() -> None:
    assert html_to_text("<script></script>a<style>b</style>c<script>d</script>e") == "ace"


def test_parser_is_built_hardened(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}
    real = lxml_html.HTMLParser

    def spy(**kwargs: Any) -> object:
        seen.update(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(lxml_html, "HTMLParser", spy)
    html_to_text("<p>x</p>")
    assert seen["huge_tree"] is False
    assert seen["no_network"] is True
