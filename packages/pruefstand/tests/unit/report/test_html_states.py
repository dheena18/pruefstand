"""``render_html`` states (T6.4): tier 1, banners, no baseline, CSP, block and judged subset."""

import base64
import hashlib
import re
from importlib import resources

import pytest
from lxml import html as lh
from testsupport.html_builders import run_of
from testsupport.report_builders import (
    PASS,
    base_manifest,
    decision,
    gate_report,
    info_row,
    manifest,
    no_baseline_report,
    tier1_base,
    tier1_manifest,
    tier1_report,
)

from pruefstand.report import html as report_html
from pruefstand.report.html import render_html

DRIFT_TEXT = "Judge drift detected (5 or more of 50 anchor verdicts changed)"


def doc(text: str) -> lh.HtmlElement:
    return lh.document_fromstring(text)


def tier1(**changes: object) -> str:
    return render_html(tier1_report(), run_of(tier1_base()), run_of(tier1_manifest(**changes)))


def captions(text: str) -> list[str]:
    return [c.text_content().strip() for c in doc(text).xpath("//caption")]


def test_tier1_shows_checks_and_reported_tables_and_no_gated_table() -> None:
    text = tier1()
    caps = captions(text)
    assert "Checks (decide)" in caps
    assert "Reported — does not decide at n = 20" in caps
    assert not any(c.startswith("Gated metrics") for c in caps)
    assert "Tier 1" in text
    assert "GPU-s" not in text
    checks = doc(text).xpath("//caption[normalize-space()='Checks (decide)']")[0].getparent()
    rows = [r.xpath("./*")[0].text_content().strip() for r in checks.xpath("./tbody/tr")]
    assert rows == ["Hard fails (canary, tenant, system prompt)", "Error rate"]


def test_tier1_reported_rows_have_no_status_word_and_injection_is_reported() -> None:
    root = doc(tier1())
    reported = root.xpath("//caption[starts-with(.,'Reported')]")[0].getparent()
    text = reported.text_content()
    assert "injection reported in tier 1" in text
    assert "reported in tier 1" in text
    assert not re.search(r"\b(PASS|WARN|FAIL)\b", text)
    info = root.xpath("//caption[normalize-space()='Informational (does not block)']")[
        0
    ].getparent()
    assert "refusal gated only in nightly full" in info.text_content()


def test_tier1_judged_heading_names_github_models_and_subset() -> None:
    text = tier1(judge_mode="github", judged_cases=10, judged_subset=True)
    assert "GitHub Models" in text
    assert "judged subset (150 cases)" in text
    assert "Judged metrics — informational, does not block (GitHub Models, 10 cases)" in text


def test_judge_skipped_replaces_the_judged_heading() -> None:
    text = tier1(judge_mode="skipped")
    assert "Judge skipped (quota used up)" in text
    assert "Judged metrics — informational" not in text
    keys = re.findall(r'data-key="(faithfulness|answer_correctness)\|', text)
    assert sorted(keys) == ["answer_correctness", "faithfulness"]  # rows stay visible, once


BANNERS = {
    "judge_fallback": "Some judgments came from the fallback judge",
    "judge_degraded": "The judge failed on more than 5 % of cases",
    "judge_drift": DRIFT_TEXT,
}


@pytest.mark.parametrize("flag", sorted(BANNERS))
def test_judge_flags_render_their_banner_and_are_absent_when_false(flag: str) -> None:
    base, report = run_of(base_manifest()), gate_report()
    on = render_html(report, base, run_of(manifest(**{flag: True})))
    off = render_html(report, base, run_of(manifest(**{flag: False})))
    assert BANNERS[flag] in on
    assert BANNERS[flag] not in off
    assert "0.85" not in on
    assert "recalibration" not in on
    assert "run-gate" not in on


def test_judge_skipped_banner_only_when_skipped() -> None:
    base, report = run_of(base_manifest()), gate_report()
    assert "Judge skipped" in render_html(report, base, run_of(manifest(judge_mode="skipped")))
    assert "Judge skipped" not in render_html(report, base, run_of(manifest()))


def test_incomplete_run_banner() -> None:
    cand = run_of(manifest(complete=False, stop_reason="budget_exceeded"))
    text = render_html(gate_report(), run_of(base_manifest()), cand)
    assert "Incomplete run — not gated (stop reason: budget_exceeded)." in text


def test_no_baseline_state_without_baseline_run() -> None:
    text = render_html(no_baseline_report(), None, run_of(manifest()))
    assert "⚪" in text
    assert "NO BASELINE" in text
    assert 'Baseline: <span class="mono">–</span>' in text
    assert (
        "No baseline for this evaluation fingerprint — nothing was compared. Run baseline-promote."
        in text
    )
    assert not any(c.startswith(("Gated", "Checks", "Informational")) for c in captions(text))
    assert "Baseline answer" not in text
    assert doc(text).xpath("//caption[normalize-space()='Run metadata']")


def test_baseline_id_in_mono_when_only_the_id_is_known() -> None:
    report = gate_report(baseline_run_id="20261101T220000-ba5e00")
    text = render_html(report, None, run_of(manifest()))
    assert '<span class="mono">20261101T220000-ba5e00</span>' in text
    assert "Baseline answer" not in text
    assert "−0.07 (−0.10, −0.04)" in text  # base and delta still come from the decision


def meta_of(text: str) -> tuple[lh.HtmlElement, list[lh.HtmlElement]]:
    head = doc(text).head
    assert head is not None
    return head, head.xpath("./meta[@http-equiv='Content-Security-Policy']")


def csp_hash(content: str) -> str:
    match = re.search(r"script-src 'sha256-([A-Za-z0-9+/=]+)'", content)
    assert match, content
    return match.group(1)


@pytest.mark.parametrize("with_base", [True, False])
def test_csp_meta_is_first_in_head_and_hashes_the_inline_script(*, with_base: bool) -> None:
    base = run_of(base_manifest()) if with_base else None
    report = gate_report() if with_base else no_baseline_report()
    text = render_html(report, base, run_of(manifest()))
    head, metas = meta_of(text)
    assert len(metas) == 1
    assert head[0] is metas[0]
    content = metas[0].get("content") or ""
    assert content == (
        f"default-src 'none'; style-src 'unsafe-inline'; script-src 'sha256-{csp_hash(content)}'; "
        "img-src data:; base-uri 'none'; form-action 'none'"
    )
    scripts = doc(text).xpath("//script")
    assert len(scripts) == 1
    body = scripts[0].text
    digest = base64.b64encode(hashlib.sha256(body.encode()).digest()).decode()
    assert csp_hash(content) == digest
    assert "frame-ancestors" not in content


def test_inline_script_is_sort_js_byte_for_byte() -> None:
    raw = (resources.files("pruefstand.report") / "templates" / "_sort.js").read_bytes()
    assert len(raw) <= 5 * 1024
    assert b"</script" not in raw
    text = render_html(gate_report(), run_of(base_manifest()), run_of(manifest()))
    assert f"<script>{raw.decode()}</script>" in text


def test_patched_script_changes_the_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    args = (gate_report(), run_of(base_manifest()), run_of(manifest()))
    before = csp_hash(meta_of(render_html(*args))[1][0].get("content") or "")
    real = report_html._asset
    monkeypatch.setattr(
        report_html, "_asset", lambda n: b"/* patched */\n" if n == "_sort.js" else real(n)
    )
    patched = render_html(*args)
    after = csp_hash(meta_of(patched)[1][0].get("content") or "")
    assert after != before
    assert "<script>/* patched */\n</script>" in patched


def test_block_and_gated_status_title() -> None:
    text = render_html(
        gate_report(status=PASS, hard_fails=(), decisions=(decision(status=PASS),)),
        run_of(base_manifest()),
        run_of(manifest(block=2, workload="nightly")),
    )
    assert "full block 2" not in text
    assert "core, robust_pr block 2" in text
    assert "✅" in text
    assert "0 blocking issues" in text


def test_unknown_reason_code_is_shown_raw_and_never_dropped() -> None:
    report = gate_report(
        decisions=(info_row("language_match", "weird_new_reason", 0.9, 0.8, diff=-0.1),)
    )
    text = render_html(report, run_of(base_manifest()), run_of(manifest()))
    assert "weird_new_reason" in text
