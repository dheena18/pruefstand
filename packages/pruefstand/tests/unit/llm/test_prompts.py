import hashlib
from pathlib import Path

import pytest

import pruefstand.llm
from pruefstand.core.errors import PromptError
from pruefstand.llm.prompts import PromptRegistry

PROMPT_DIR = Path(pruefstand.llm.__file__).parent / "prompts"


def test_echo_renders_system_and_user() -> None:
    messages = PromptRegistry().get("echo", "v1").render(word="Müller")
    assert [m.role for m in messages] == ["system", "user"]
    assert "Müller" in messages[1].content
    assert "{{" not in messages[0].content + messages[1].content


def test_missing_variable_raises() -> None:
    with pytest.raises(PromptError, match="word"):
        PromptRegistry().get("echo", "v1").render()


def test_extra_variable_raises() -> None:
    with pytest.raises(PromptError, match="extra"):
        PromptRegistry().get("echo", "v1").render(word="a", extra="b")


def test_sha256_is_over_file_bytes() -> None:
    expected = hashlib.sha256((PROMPT_DIR / "echo_v1.txt").read_bytes()).hexdigest()
    template = PromptRegistry().get("echo", "v1")
    assert template.sha256 == expected
    assert (template.prompt_id, template.version) == ("echo", "v1")


def test_unknown_version_raises() -> None:
    with pytest.raises(PromptError, match="v9"):
        PromptRegistry().get("echo", "v9")


def test_json_probe_prompt_mentions_the_schema_fields() -> None:
    messages = (
        PromptRegistry().get("json_probe", "v1").render(sentence="Die Kündigung ist wirksam.")
    )
    text = " ".join(m.content for m in messages)
    assert "reason" in text
    assert "score" in text
    assert "Kündigung" in text


def test_custom_root_and_malformed_file(tmp_path: Path) -> None:
    (tmp_path / "bad_v1.txt").write_text("kein Abschnitt\n", encoding="utf-8")
    (tmp_path / "ok_v1.txt").write_text("### user\nHallo {{ name }}!\n", encoding="utf-8")
    registry = PromptRegistry([tmp_path])
    with pytest.raises(PromptError, match="###"):
        registry.get("bad", "v1")
    messages = registry.get("ok", "v1").render(name="Welt")
    assert [m.role for m in messages] == ["user"]
    assert messages[0].content == "Hallo Welt!"


def test_substituted_value_is_not_expanded_again(tmp_path: Path) -> None:
    (tmp_path / "t_v1.txt").write_text("### user\n{{a}} {{b}}\n", encoding="utf-8")
    messages = PromptRegistry([tmp_path]).get("t", "v1").render(a="{{b}}", b="x")
    assert messages[0].content == "{{b}} x"


@pytest.mark.parametrize("prompt_id", ["../echo", "a/b", "Echo", "", "echo\x00", "ec ho", "..\\x"])
def test_prompt_id_cannot_escape_the_roots(prompt_id: str) -> None:
    with pytest.raises(PromptError, match="prompt_id"):
        PromptRegistry().get(prompt_id, "v1")


def test_dotted_ids_are_fine() -> None:
    with pytest.raises(PromptError, match="not found"):
        PromptRegistry().get("datagen.private_docs.x", "v1")
