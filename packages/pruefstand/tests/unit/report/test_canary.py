"""Canary tokens never reach the comment, whatever invisible characters or separators hide them."""

import re
import time

import pytest
from testsupport.report_builders import decision, gate_report, hard_fail
from testsupport.report_render import render

from pruefstand.report.format import md_code, md_escape

SPLIT = [
    "CAN\u200bARY-VN-7f3a9c",
    "CANARY-VN\u200b-7f3a9c",
    "CANARY-VN7f3a9c",
    "CANARYVN7f3a9c",
    "canary.vn.7f3a9c",
    "CANARY\u2013VN\u20137f3a9c",
    "\uff23\uff21\uff2e\uff21\uff32\uff39-\uff36\uff2e-\uff17\uff46\uff13\uff41\uff19\uff43",
    "C\u034fANARY-VN-7f3a9c",
    "CANARY-VN-7f\u00ad3a9c",
    "C A N A R Y - V N - 7 f 3 a 9 c",
    "CANARY-VN-7F3A9C",
]
HEX = re.compile(r"7f.?3a9c|3a9c|7f3a", re.IGNORECASE)


@pytest.mark.parametrize("raw", SPLIT)
def test_helpers_mask_every_spelling(raw: str) -> None:
    for out in (md_code(f"vor {raw} nach"), md_escape(f"vor {raw} nach")):
        assert not HEX.search(out), out
        assert "vor" in out
        assert "CANARY-" in out


@pytest.mark.parametrize("raw", SPLIT)
def test_hard_fail_row_slice_value_and_case_id_are_masked(raw: str) -> None:
    finding = hard_fail().model_copy(update={"evidence": f"... {raw} ..."})
    row = decision(dimension="tags", value=raw, status="warn")  # type: ignore[arg-type]
    report = gate_report(hard_fails=(finding,), decisions=(row,), top_failing_cases=(raw,))
    assert not HEX.search(render(report))


def test_legitimate_canary_words_survive() -> None:
    assert md_escape("canary_leak") == "canary_leak"
    assert md_code("canary_leak") == "`canary_leak`"
    assert md_escape("Canary leak (none)") == "Canary leak \\(none\\)"
    out = render(gate_report())
    assert "| canary_leak | law-0107 | canary_leak |" in out


def test_masking_is_linear() -> None:
    def cost(n: int) -> float:
        text = "CAN\u200bARY-VN-7f3a9c x " * n
        best = float("inf")
        for _ in range(3):
            t0 = time.perf_counter()
            md_code(text, limit=len(text))
            best = min(best, time.perf_counter() - t0)
        return best

    assert cost(1_600) <= 8 * max(cost(400), 1e-4)
