import pytest
from testsupport.timing import assert_scales_linearly, cpu_budget

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


def _extract_none(text: str) -> None:
    assert extract_json_object(text) is None


def test_many_opening_braces_scale_linearly() -> None:
    small, large = "{" * 50_000, "{" * 200_000
    assert_scales_linearly(lambda: _extract_none(small), lambda: _extract_none(large), scale=4)


def test_a_megabyte_of_braces_returns_quickly() -> None:
    with cpu_budget(2.0):
        _extract_none("{" * 1_000_000)


def test_input_beyond_the_cap_is_not_scanned() -> None:
    assert extract_json_object("x" * 300_000 + '{"a": 1}') is None
