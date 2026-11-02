"""Canary tokens never reach the comment, whatever invisible characters or separators hide them."""

import re
import time

import pytest
from hypothesis import given
from hypothesis import strategies as st
from testsupport.report_builders import decision, gate_report, hard_fail
from testsupport.report_render import render

from pruefstand.metrics.deterministic.normalise import security_normalise
from pruefstand.report.format import md_code, md_escape

TOKEN_RE = re.compile(r"canary-[a-z]{2}-[0-9a-f]{6}")

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
    "\u0441ANARY-VN-7f3a9c",
    "C\u0410NARY-VN-7f3a9c",
    "\u0441\u0430n\u0430ry-vn-7f3a9c",
    "c\u03b1n\u03b1ry-vn-7f3a9c",
    "CAN\u3164ARY-VN-7f3a9c",
    "CANARY-VN-7f3\u115fa9c",
    "CANARY\uffa0VN-7f3a9c",
    "CAN\u1160ARY-VN-7f3a9c",
]
FIRST = "CANARY-VN-7f3a9c"
SECOND = "CANARY-KM-0d1e2f"
HEX = re.compile(r"7f.?3a9c|3a9c|7f3a|0d1e2f|0d1e", re.IGNORECASE)


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
        text = "CAN\u200bARY-VN-7f3a9cCANARY-KM-0d1e2f x " * n
        best = float("inf")
        for _ in range(3):
            t0 = time.perf_counter()
            md_code(text, limit=len(text))
            best = min(best, time.perf_counter() - t0)
        return best

    assert cost(1_600) <= 8 * max(cost(400), 1e-4)


@pytest.mark.parametrize("joiner", [" ", ", ", "\n", "", "12", "\u200b", " und "])
def test_adjacent_tokens_are_all_masked(joiner: str) -> None:
    text = f"Leak: {FIRST}{joiner}{SECOND}"
    for out in (md_code(text), md_escape(text)):
        assert not HEX.search(out), out
        assert out.count("CANARY-") >= 2


def test_adjacent_tokens_in_the_rendered_comment() -> None:
    finding = hard_fail().model_copy(update={"evidence": f"{FIRST} {SECOND}{FIRST}"})
    assert not HEX.search(render(gate_report(hard_fails=(finding,))))


PIECES = st.sampled_from(["C", "\u0421", "\u0441", "c", "A", "\u0410", "\u03b1", "a"])
FILL = st.sampled_from(["", "-", " ", ".", "\u200b", "\u3164", "\u115f", "\uffa0", "\u00ad", "_"])


@given(
    fills=st.lists(FILL, min_size=6, max_size=6),
    lead=st.sampled_from(["C", "\u0421", "c"]),
    a1=st.sampled_from(["A", "\u0410", "a", "\u03b1"]),
    hex_=st.from_regex(r"[0-9a-f]{6}", fullmatch=True),
    kind=st.sampled_from(["VN", "km", "Xy"]),
)
def test_parity_with_the_detector(
    fills: list[str], lead: str, a1: str, hex_: str, kind: str
) -> None:
    f = fills
    text = f"{lead}{f[0]}{a1}{f[1]}N{f[2]}{a1}{f[3]}R{f[4]}Y{f[5]}{kind}{hex_}"
    if TOKEN_RE.search(security_normalise(text)):
        for out in (md_code(text), md_escape(text)):
            assert not TOKEN_RE.search(security_normalise(out)), (text, out)
