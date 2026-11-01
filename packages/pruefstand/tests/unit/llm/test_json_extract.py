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
