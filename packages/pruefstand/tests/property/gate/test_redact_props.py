"""Property test: ``redact_evidence`` masks every spelling the leak detector would catch (T1.7b)."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pruefstand.core.canary import CANARY_MASK, CONFUSABLES
from pruefstand.gate.hard_fail import redact_evidence

_LOOKALIKES: dict[str, list[str]] = {}
for _code, _latin in CONFUSABLES.items():
    _LOOKALIKES.setdefault(_latin, []).append(chr(_code))

_FILLERS = ["", "", "", "\u200b", "­", "⁠", "ㅤ", "ᅟ", "﻿", "͏"]
_GROUP_SEPARATORS = ["", "-", "_", ".", " ", "–", "—", "\u200b-", "ㅤ", "--", " . "]
_HEX_SEPARATORS = ["", "", "", "-", ".", "–", "_"]
_MARKS = ["", "", "", "́", "̈"]
CLEAN = "Antwort: {} Ende"


def _spell_char(draw: st.DrawFn, ch: str, *, last: bool = False) -> str:
    """Spell one character; the very last one of a token gets no trailing mark or filler."""
    options = [ch, ch.upper(), chr(ord(ch) + 0xFEE0), chr(ord(ch.upper()) + 0xFEE0)]
    options += _LOOKALIKES.get(ch, [])
    if not ch.isdigit():
        options += [c.upper() for c in _LOOKALIKES.get(ch, [])]
    spelled = draw(st.sampled_from(options))
    return spelled if last else spelled + draw(st.sampled_from(_MARKS))


@st.composite
def spelled_tokens(draw: st.DrawFn) -> str:
    """One canary token: ``canary`` + two letters + six hex digits, spelled in a hostile way."""
    letters = draw(st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=2, max_size=2))
    digits = draw(st.text(alphabet="0123456789abcdef", min_size=6, max_size=6))
    parts: list[str] = []
    for n, (group, seps) in enumerate(
        (("canary", _HEX_SEPARATORS), (letters, _HEX_SEPARATORS), (digits, _HEX_SEPARATORS))
    ):
        is_last = n == 2
        chars = [
            _spell_char(draw, c, last=is_last and i == len(group) - 1)
            + ("" if is_last and i == len(group) - 1 else draw(st.sampled_from(_FILLERS)))
            for i, c in enumerate(group)
        ]
        joined = chars[0]
        for ch in chars[1:]:
            joined += draw(st.sampled_from(seps)) + ch
        parts.append(joined)
    first = draw(st.sampled_from(_GROUP_SEPARATORS))
    second = draw(st.sampled_from(_GROUP_SEPARATORS))
    return parts[0] + first + parts[1] + second + parts[2]


@given(spelled_tokens())
def test_every_spelling_is_masked(token: str) -> None:
    assert redact_evidence(CLEAN.format(token)) == CLEAN.format(CANARY_MASK)


@given(spelled_tokens(), spelled_tokens(), st.sampled_from(["", " ", " und ", "\u200b"]))
def test_two_adjacent_tokens_are_both_masked(first: str, second: str, glue: str) -> None:
    redacted = redact_evidence(CLEAN.format(first + glue + second))
    assert redacted.count(CANARY_MASK) == 2
    assert redacted.startswith("Antwort: ")
    assert redacted.endswith(" Ende")


@pytest.mark.parametrize(
    "spelling",
    [
        "CAN\u200bARY-VN-7f3a9c",
        "CANARY-VN7f3a9c",
        "CANARYVN7f3a9c",
        "canary.vn.7f3a9c",
        "CANARY–VN–7f3a9c",
        "ＣＡＮＡＲＹ-VN-7f3a9c",
        "CÁNARY-VN-7f3a9c",
        "CANARYㅤ-VN-7f3a9c",
        "CANARY-VN-7F3A9C",
    ],
)
def test_named_spellings(spelling: str) -> None:
    assert redact_evidence(CLEAN.format(spelling)) == CLEAN.format(CANARY_MASK)


def test_adjacent_tokens_without_separator() -> None:
    text = "CANARY-VN-7f3a9cCANARY-AB-0123ab"
    assert redact_evidence(text) == CANARY_MASK + CANARY_MASK


def test_text_without_a_token_is_unchanged() -> None:
    assert redact_evidence("Der Kanarienvogel singt.") == "Der Kanarienvogel singt."
