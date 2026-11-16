"""T8.4: the kill switch is read per call, from the env or a flag file."""

from pathlib import Path

import pytest

from rag_demo.public.killswitch import demo_disabled


@pytest.mark.parametrize("value", ["false", "FALSE", "0", "no", "off", " False "])
def test_demo_enabled_false_switches_the_demo_off(value: str, tmp_path: Path) -> None:
    assert demo_disabled({"DEMO_ENABLED": value}, tmp_path / "none") is True


@pytest.mark.parametrize("env", [{}, {"DEMO_ENABLED": "true"}, {"DEMO_ENABLED": "1"}])
def test_the_demo_is_on_by_default(env: dict[str, str], tmp_path: Path) -> None:
    assert demo_disabled(env, tmp_path / "none") is False


def test_the_flag_file_switches_it_off_and_removing_it_switches_it_on(tmp_path: Path) -> None:
    flag = tmp_path / "disabled"
    assert demo_disabled({}, flag) is False
    flag.write_text("", encoding="utf-8")
    assert demo_disabled({}, flag) is True  # checked per call, no restart
    flag.unlink()
    assert demo_disabled({}, flag) is False


def test_the_process_environment_is_read_per_call_not_cached_at_import(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    flag = tmp_path / "none"
    monkeypatch.delenv("DEMO_ENABLED", raising=False)
    assert demo_disabled(None, flag) is False
    monkeypatch.setenv("DEMO_ENABLED", "false")
    assert demo_disabled(None, flag) is True  # set after import: a cached environ would miss it
    monkeypatch.setenv("DEMO_ENABLED", "true")
    assert demo_disabled(None, flag) is False
