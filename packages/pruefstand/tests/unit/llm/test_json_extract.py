import time

import pytest

from pruefstand.llm.json_extract import extract_json_object


def test_plain_object() -> None:
    assert extract_json_object('{"a": 1}') == '{"a": 1}'


def test_fenced_object_keeps_umlauts() -> None:
    text = '```json\n{"reason": "Kündigung unwirksam", "score": 0}\n```'
    assert extract_json_object(text) == '{"reason": "Kündigung unwirksam", "score": 0}'


def test_prose_before_and_after() -> None:
    assert extract_json_object('Hier: {"a": {"b": 2}} fertig.') == '{"a": {"b": 2}}'


def test_braces_inside_strings_do_not_count() -> None:
    text = 'x {"a": "}{\\"", "b": 1} y'
    assert extract_json_object(text) == '{"a": "}{\\"", "b": 1}'


@pytest.mark.parametrize("text", ["", "kein json", '{"a": 1', "}{"])
def test_no_complete_object_returns_none(text: str) -> None:
    assert extract_json_object(text) is None


def test_placeholder_braces_do_not_hide_the_object() -> None:
    assert extract_json_object('Beispiel {Platzhalter} und {"a":1}') == '{"a":1}'


def test_only_valid_json_is_returned() -> None:
    assert extract_json_object('{a: 1} {"b": [1, 2]}') == '{"b": [1, 2]}'


def _seconds(text: str) -> float:
    start = time.perf_counter()
    assert extract_json_object(text) is None
    return time.perf_counter() - start


def test_many_opening_braces_scale_linearly() -> None:
    small = min(_seconds("{" * 50_000) for _ in range(3))
    large = min(_seconds("{" * 200_000) for _ in range(3))
    assert large < 2.0
    assert large <= 8 * max(small, 0.005)  # 4x the input, at most 8x the time


def test_a_megabyte_of_braces_returns_quickly() -> None:
    assert _seconds("{" * 1_000_000) < 2.0


def test_input_beyond_the_cap_is_not_scanned() -> None:
    assert extract_json_object("x" * 300_000 + '{"a": 1}') is None
