"""``family_of`` and the family-plan loader check (S8, W3.1, ADR-0019)."""

from pathlib import Path

import pytest
import yaml
from testsupport.gpu_files import SHIPPED_CATALOGUE

from pruefstand.core.errors import ConfigError
from pruefstand.llm.families import family_of, validate_family_plan


def _write(path: Path, entries: list[dict[str, object]]) -> Path:
    path.write_text(yaml.safe_dump({"models": entries}), encoding="utf-8")
    return path


def _entry(mid: str, role: str, family: str) -> dict[str, object]:
    return {"id": mid, "engine": "ollama", "role": role, "family": family}


def test_catalogue_models_map_to_their_family() -> None:
    assert family_of("ollama/gemma3:12b") == "gemma"
    assert family_of("ollama/qwen3.8:27b-q8_0") == "qwen"
    assert family_of("github/openai/gpt-4.1-mini") == "gpt"


def test_a_distill_pattern_maps_to_its_base_family() -> None:
    assert family_of("github/deepseek/DeepSeek-R1-Distill-Qwen-7B") == "qwen"


def test_an_unknown_model_is_a_config_error() -> None:
    with pytest.raises(ConfigError, match="mystery"):
        family_of("github/acme/mystery-9b")


def test_every_catalogue_entry_family_equals_family_of_its_id() -> None:
    entries = yaml.safe_load(SHIPPED_CATALOGUE.read_text(encoding="utf-8"))["models"]
    assert entries
    for entry in entries:
        assert entry["family"] == family_of(entry["id"]), entry["id"]


def test_the_shipped_catalogue_and_plan_pass() -> None:
    validate_family_plan(SHIPPED_CATALOGUE)


def test_a_generator_of_another_family_than_the_plan_fails(tmp_path: Path) -> None:
    path = _write(tmp_path / "m.yaml", [_entry("ollama/gemma3:12b", "generator", "gemma")])
    with pytest.raises(ConfigError, match="generator"):
        validate_family_plan(path)


def test_a_judge_of_the_generator_family_fails(tmp_path: Path) -> None:
    path = _write(tmp_path / "m.yaml", [_entry("ollama/qwen3:4b", "judge", "qwen")])
    with pytest.raises(ConfigError, match="judge"):
        validate_family_plan(path)


@pytest.mark.parametrize("role", ["nightly_judge", "large"])
def test_roles_removed_by_adr_0019_fail(tmp_path: Path, role: str) -> None:
    path = _write(tmp_path / "m.yaml", [_entry("ollama/gemma3:12b", role, "gemma")])
    with pytest.raises(ConfigError, match=role):
        validate_family_plan(path)


def test_a_tier1_judge_of_the_qwen_family_fails(tmp_path: Path) -> None:
    path = _write(tmp_path / "m.yaml", [_entry("ollama/gemma3:12b", "judge", "gemma")])
    with pytest.raises(ConfigError, match="tier"):
        validate_family_plan(path, plan={"generator": "qwen", "judge_tier1": "qwen"})
