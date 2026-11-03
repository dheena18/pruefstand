"""``render_html`` (T6.4): structure, safety, accessibility and the content rules of ui-spec §13."""

import json
import re
from importlib import resources
from typing import Any

import pytest
from lxml import html as lh
from testsupport.html_builders import CHUNK_TEXT, QUESTION, run_of, tier2_pair
from testsupport.report_builders import (
    FAIL,
    INSUFFICIENT,
    PASS,
    absolute_row,
    base_manifest,
    decision,
    gate_report,
    info_row,
    manifest,
    notable_row,
)

from pruefstand.core.models.gate import GateReport
from pruefstand.report.html import render_html


def rich_report() -> GateReport:
    rows = (
        decision(cand=0.77, ci=(-0.09, -0.12, -0.06), mde=0.06),
        decision("faithfulness", status=PASS, base=0.9, cand=0.89, ci=(-0.01, -0.03, 0.01)),
        decision(dimension="tenant", value="kanzlei_mueller", ci=(-0.07, -0.11, -0.03)),
        decision(dimension="tenant", value="stadtwerke_sued", status=INSUFFICIENT, n_clusters=22),
    )
    return gate_report(
        decisions=rows,
        absolute_checks=(absolute_row("injection_success", 0.03, FAIL),),
        notable_slices=(notable_row("perturbation", "compound_split", -0.18),),
        likely_cause="retrieval",
        not_applicable_counts={"citation_f1": 3},
    )


def render(report: GateReport | None = None, **cand_changes: Any) -> str:
    base, cand = tier2_pair(**cand_changes)
    return render_html(report or rich_report(), base, cand)


def doc(text: str) -> lh.HtmlElement:
    return lh.document_fromstring(text)


def test_umlauts_and_german_text_render_as_utf8() -> None:
    text = render()
    assert QUESTION in text
    assert "Kündigungsschutzgesetz § 23" in text  # chunk text of a private render
    assert "Prüfstand report" in text


def test_header_has_status_tier_blocking_cause_and_facts() -> None:
    text = render()
    assert "❌" in text
    assert "FAIL" in text
    assert "Tier 2" in text
    assert "4 blocking issues" in text
    assert "Likely cause: retrieval" in text
    assert "Baseline: <span" in text
    assert "main@a1b2c3d" in text
    assert "pr-42@d4e5f6a" in text
    assert "core, robust_pr" in text
    assert "790 cases" in text
    assert "4.1 M tokens" in text
    assert "~2,100 GPU-s" in text
    assert "created 2026-11-02 22:00 UTC" in text
    assert '<html lang="en">' in text


def test_html_in_every_untrusted_string_is_escaped() -> None:
    evil = "<script>alert(1)</script><img src=x onerror=alert(2)>"
    base = run_of(base_manifest(git_ref=evil), answer=evil)
    cand = run_of(
        manifest(git_ref=evil), answer=evil, question=evil, chunk_text=evil, category="factual"
    )
    report = gate_report(
        decisions=(decision(dimension="tenant", value=evil),),
        top_failing_cases=("law-0042", "law-0107"),
    )
    text = render_html(report, base, cand)
    assert "<img" not in text.replace("&lt;img", "")
    assert evil not in text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in text
    root = doc(text)
    assert len(root.xpath("//script")) == 1
    assert not [a for el in root.iter() for a in el.attrib if a.startswith("on")]


def test_no_external_resource_and_no_event_handler() -> None:
    text = render()
    root = doc(text)
    assert not root.xpath("//link")
    assert not root.xpath("//*[@src]")
    assert all(a.get("href", "#").startswith("#") for a in root.xpath("//a"))
    assert not re.findall(r"(?:src|href)=[\"']https?:", text)
    assert not [a for el in root.iter() for a in el.attrib if a.lower().startswith("on")]


def test_every_table_has_caption_and_scoped_headers() -> None:
    root = doc(render())
    tables = root.xpath("//table")
    assert len(tables) >= 6
    for t in tables:
        assert t.xpath("./caption"), "table without caption"
        for th in t.xpath(".//th"):
            assert th.get("scope") in {"col", "row"}


def test_sortable_headers_are_buttons_with_aria_sort() -> None:
    root = doc(render())
    sortable = root.xpath("//table[@data-sortable]")
    assert sortable
    for t in sortable:
        heads = t.xpath("./thead//th")
        assert heads
        for th in heads:
            assert th.get("aria-sort") == "none"
            assert th.xpath("./button[@type='button']")


def test_gated_metric_table_has_seven_columns_with_delta_and_mde() -> None:
    root = doc(render())
    caption = root.xpath("//caption[normalize-space()='Gated metrics (overall)']")[0]
    table = caption.getparent()
    heads = [th.text_content().strip() for th in table.xpath("./thead//th")]
    assert heads == ["Metric", "Base", "PR", "Δ (95% CI)", "δ", "MDE", "Status"]
    first = [c.text_content().strip() for c in table.xpath("./tbody/tr[1]/*")]
    assert first == [
        "Context recall",
        "0.86",
        "0.77",
        "−0.09 (−0.12, −0.06)",
        "0.05",
        "0.06",
        "❌ FAIL",
    ]


def test_absolute_check_shows_value_and_max() -> None:
    root = doc(render())
    table = root.xpath("//caption[normalize-space()='Absolute checks']")[0].getparent()
    cells = [c.text_content().strip() for c in table.xpath("./tbody/tr[1]/*")]
    assert cells == ["Injection success", "0.03", "0.02", "❌ FAIL"]


def test_slices_insufficient_greyed_notable_marked_not_applicable_listed() -> None:
    root = doc(render())
    slices = root.xpath("//caption[normalize-space()='Gated slices']")[0].getparent()
    greyed = slices.xpath("./tbody/tr[@class='dim']")
    assert len(greyed) == 1
    assert "stadtwerke_sued" in greyed[0].text_content()
    notable = root.xpath("//caption[contains(.,'Notable slices')]")[0].getparent()
    assert "informational, does not block" in notable.xpath("./caption")[0].text_content()
    assert "compound_split" in notable.text_content()
    assert "notable" in notable.text_content()
    na = root.xpath("//caption[normalize-space()='Not applicable']")[0].getparent()
    assert "Citation F1" in na.text_content()
    assert "3" in na.text_content()


def test_every_decision_is_in_exactly_one_table() -> None:
    report = rich_report()
    report = report.model_copy(
        update={
            "decisions": (
                *report.decisions,
                info_row("refusal_correct", "refusal_outside_nightly_full", 1.0, 1.0, diff=0.0),
            )
        }
    )
    text = render(report)
    every = (*report.decisions, *report.absolute_checks, *report.notable_slices)
    keys = [f"{d.metric}|{d.dimension}|{d.value}" for d in every]
    assert len(set(keys)) == len(keys)
    for key in keys:
        assert len(re.findall(f'data-key="{re.escape(key)}"', text)) == 1, key


def test_informational_decision_is_listed_with_its_reason() -> None:
    report = gate_report(
        decisions=(
            info_row("refusal_correct", "refusal_outside_nightly_full", 1.0, 0.9, diff=-0.1),
        )
    )
    root = doc(render(report))
    table = root.xpath("//caption[normalize-space()='Informational (does not block)']")[
        0
    ].getparent()
    row = table.xpath("./tbody/tr")[0].text_content()
    assert "refusal gated only in nightly full" in row
    assert not re.search(r"PASS|WARN|FAIL", row)  # informational rows show no status word


def test_top_failing_cases_cards_are_capped_and_carry_citations_and_lang() -> None:
    ids = tuple(f"law-{i:04d}" for i in range(30))
    base = run_of(base_manifest(), tuple(range(30)))
    cand = run_of(manifest(), tuple(range(30)), lang="en", question="Does the act apply?")
    text = render_html(gate_report(top_failing_cases=ids), base, cand)
    root = doc(text)
    assert len(root.xpath("//article[@class='card']")) == 20
    first = root.xpath("//article[@class='card']")[0]
    assert first.xpath(".//p[@class='text'][@lang='en']")
    assert "§ 23 KSchG" in first.xpath(".//ul[@lang='de']")[0].text_content()
    assert "Baseline answer" in first.text_content()


def test_german_case_marks_question_and_answer_as_de() -> None:
    root = doc(render())
    card = root.xpath("//article[@class='card']")[0]
    assert card.xpath(".//p[@class='text'][@lang='de']")
    assert card.xpath(".//div[@lang='de']")


def test_chunk_cards_mark_unused_chunks_and_foreign_tenants() -> None:
    cand = run_of(manifest(), tenant="kanzlei_mueller")
    text = render_html(gate_report(), run_of(base_manifest()), cand)
    assert "not used in prompt" in text
    assert text.count("not used in prompt") == 2  # rank 2 of each of the two cases
    assert "Retrieved chunks (rank order)" in text


def test_sanitised_style_render_has_no_chunk_text_and_no_canary() -> None:
    # empty chunk text is what sanitise_run leaves behind
    cand = run_of(manifest(), chunk_text="")
    text = render_html(gate_report(), run_of(base_manifest(), chunk_text=""), cand)
    assert CHUNK_TEXT not in text
    assert "Chunk text is not published" in text
    assert "CANARY-" not in text


def test_print_stylesheet_and_dark_mode_are_inline() -> None:
    text = render()
    assert "@media print" in text
    assert "prefers-color-scheme:dark" in text
    assert "--pass-fg:#15803d" in text


def test_report_is_small_for_1500_cases() -> None:
    n = 1500
    base = run_of(base_manifest(), tuple(range(n)))
    cand = run_of(manifest(), tuple(range(n)))
    ids = tuple(f"law-{i:04d}" for i in range(n))
    text = render_html(gate_report(top_failing_cases=ids), base, cand)
    assert len(text.encode("utf-8")) < 2 * 1024 * 1024


def test_no_certificate_wording_and_never_compliant() -> None:
    text = render()
    assert "Supports documentation, not a compliance certificate." in text
    low = text.lower()
    assert "compliant" not in low
    assert "konform" not in low
    assert "run-gate" not in low


def test_footer_carries_the_licence_line_of_the_package_data() -> None:
    data = json.loads(
        (resources.files("pruefstand.report") / "templates" / "_licences.json").read_text("utf-8")
    )
    text = render()
    footer = doc(text).xpath("//footer")[0].text_content()
    assert data["footer_line"]["en"] in footer
    assert all(s["name"] in footer for s in data["sources"])


def test_judge_truncated_cases_are_counted_and_listed() -> None:
    base = run_of(base_manifest())
    cand = run_of(manifest(counts={"ok": 2, "judge_truncated": 2}), truncated=(42, 107))
    text = render_html(gate_report(), base, cand)
    assert "Judge input truncated on 2 cases" in text
    assert "<code>law-0042</code>, <code>law-0107</code>" in text


@pytest.mark.parametrize("block", [2, None])
def test_block_shown_in_header_only_when_set(block: int | None) -> None:
    text = render(block=block)
    assert ("block 2" in text) is (block == 2)
