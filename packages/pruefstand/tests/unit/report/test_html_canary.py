"""No canary token reaches ``report.html``, whatever hides it (parity with the detector, D448)."""

import re
from pathlib import Path

import pytest
from testsupport.html_builders import run_of
from testsupport.report_builders import base_manifest, gate_report, hard_fail, manifest
from testsupport.run_builders import make_case
from testsupport.store_support import registry, results_for, run_id, token

from pruefstand.core.models.run import RunArtifacts
from pruefstand.report.html import render_html
from pruefstand.store.sanitise import sanitise_run

SPELLINGS = [
    "CAN\u200bARY-VN-7f3a9c",
    "CANARY-VN7f3a9c",
    "canary.vn.7f3a9c",
    "CANARY–VN–7f3a9c",
    "ＣＡＮＡＲＹ-ＶＮ-７ｆ３ａ９ｃ",
    "C A N A R Y - V N - 7 f 3 a 9 c",
    "CANARY-VN-7F3A9C",
    "сANARY-VN-7f3a9c",
    "CANARY-VN-7f­3a9c",
]
HEX = re.compile(r"7f.?3a9c|3a9c|7f3a", re.IGNORECASE)


@pytest.mark.parametrize("raw", SPELLINGS)
def test_private_render_masks_every_spelling_in_every_text_field(raw: str) -> None:
    text = f"vor {raw} nach"
    evil_ref = f"feature/{raw}"
    report = gate_report(
        hard_fails=(hard_fail().model_copy(update={"evidence": f"... {raw} ..."}),),
        top_failing_cases=("law-0042",),
    )
    base = run_of(base_manifest(git_ref=evil_ref), answer=text)
    cand = run_of(manifest(git_ref=evil_ref), answer=text, question=text, chunk_text=text)
    out = render_html(report, base, cand)
    assert not HEX.search(out)
    assert "‹masked›" in out
    assert "vor" in out


def test_sanitised_run_renders_without_chunk_text_or_canary(tmp_path: Path) -> None:
    leak = token("VN-7f3a9c")
    cases = [make_case(0), make_case(1, category="leak_probe", forbidden_strings=[leak])]
    results = results_for(cases, run_id=run_id(7), stack="a40", workload="pr", judge_mode="local")
    records = tuple(
        rec.model_copy(
            update={"response": rec.response.model_copy(update={"answer": f"Es ist {leak}."})}
        )
        for rec in results.records
        if rec.response
    )
    run = RunArtifacts(results=results.model_copy(update={"records": records}), root=tmp_path)
    clean = sanitise_run(run, registry("VN-7f3a9c"))
    report = gate_report(top_failing_cases=("law-0000",))
    private = render_html(report, None, run.results)
    public = render_html(report, None, clean.results)
    assert "Kündigungsschutzgesetz § 23" in private
    assert "Kündigungsschutzgesetz § 23" not in public
    assert "Chunk text is not published" in public
    assert "CANARY-" not in public
    assert "CANARY-" not in private  # the mask never reads CANARY-
    assert not HEX.search(private)
