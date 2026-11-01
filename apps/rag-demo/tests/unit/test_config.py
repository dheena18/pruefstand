"""RagConfig, load_config and config_hash (T1.13 S2/S4)."""

import shutil
from pathlib import Path

import pytest
import yaml
from conftest import CONFIGS
from pydantic import ValidationError
from rag_demo.config import config_hash, load_config, parse_config
from rag_demo.models import RagConfig

BUG_FIELDS = {
    "tenant_filter_post_topk": "tenant_filter",
    "shared_public_unfiltered": "shared_public_merge",
    "no_citations": "prompt_file",
    "no_refusal": "prompt_file",
    "answer_language_en": "answer_language",
    "injection_guard_off": "injection_guard",
    "system_prompt_guard_off": "system_prompt_guard",
    "top_k_1": "top_k",
}


def _flat(data: dict[str, object], prefix: str = "") -> dict[str, object]:
    out: dict[str, object] = {}
    for key, value in data.items():
        if isinstance(value, dict):
            out.update(_flat(value, f"{prefix}{key}."))
        else:
            out[f"{prefix}{key}"] = value
    return out


def test_tier1_profile_values() -> None:
    cfg = load_config(CONFIGS / "rag.yaml")
    assert cfg.top_k == 4
    assert cfg.chunk_prompt_tokens == 256
    assert cfg.max_tokens == 256
    assert cfg.reranker == "off"
    assert cfg.generator.enable_thinking is False
    assert cfg.tenant_filter == "inside"
    assert cfg.shared_public_merge == "filtered"
    assert cfg.injection_guard == "on"
    assert cfg.system_prompt_guard == "on"
    assert cfg.answer_language == "auto"
    assert cfg.prompt_file == "prompts/answer_de_v1.txt"


def test_api_key_env_defaults_to_the_candidate_key() -> None:
    cfg = load_config(CONFIGS / "rag.yaml")
    assert cfg.generator.api_key_env == "PRUEFSTAND_CANDIDATE_API_KEY"
    assert cfg.embed.api_key_env == "PRUEFSTAND_CANDIDATE_API_KEY"


def test_enable_thinking_changes_the_hash() -> None:
    cfg = load_config(CONFIGS / "rag.yaml")
    flipped = cfg.model_copy(
        update={"generator": cfg.generator.model_copy(update={"enable_thinking": True})}
    )
    assert config_hash(flipped) != config_hash(cfg)


def test_same_config_same_hash_and_16_hex() -> None:
    first = config_hash(load_config(CONFIGS / "rag.yaml"))
    assert first == config_hash(load_config(CONFIGS / "rag.yaml"))
    assert len(first) == 16
    int(first, 16)


@pytest.mark.parametrize(("name", "field"), sorted(BUG_FIELDS.items()))
def test_every_bug_config_differs_in_exactly_one_field(name: str, field: str) -> None:
    good = _flat(yaml.safe_load((CONFIGS / "rag.yaml").read_text(encoding="utf-8")))
    bug = _flat(yaml.safe_load((CONFIGS / "bugs" / f"{name}.yaml").read_text(encoding="utf-8")))
    changed = {key for key in good.keys() | bug.keys() if good.get(key) != bug.get(key)}
    assert changed == {field}
    assert config_hash(load_config(CONFIGS / "bugs" / f"{name}.yaml")) != config_hash(
        load_config(CONFIGS / "rag.yaml")
    )


def test_all_bug_files_are_listed() -> None:
    assert {p.stem for p in (CONFIGS / "bugs").glob("*.yaml")} == set(BUG_FIELDS)


def test_unknown_key_is_an_error() -> None:
    with pytest.raises(ValidationError):
        parse_config("top_k: 4\nsurprise: 1\n")


def test_unknown_nested_key_is_an_error() -> None:
    text = (CONFIGS / "rag.yaml").read_text(encoding="utf-8") + "\n"
    broken = text.replace("generator:\n", "generator:\n  surprise: 1\n", 1)
    with pytest.raises(ValidationError):
        parse_config(broken)


def test_top_k_bounds() -> None:
    with pytest.raises(ValidationError):
        RagConfig.model_validate({"top_k": 0})
    with pytest.raises(ValidationError):
        RagConfig.model_validate({"top_k": 51})


def test_one_changed_character_in_the_prompt_changes_the_hash(tmp_path: Path) -> None:
    cfg = load_config(CONFIGS / "rag.yaml")
    package_prompts = Path(__import__("rag_demo").__file__).parent / "prompts"
    shutil.copytree(package_prompts, tmp_path / "prompts")
    before = config_hash(cfg, prompts_root=tmp_path)
    target = tmp_path / "prompts" / "answer_de_v1.txt"
    target.write_text(target.read_text(encoding="utf-8") + ".", encoding="utf-8")
    assert config_hash(cfg, prompts_root=tmp_path) != before
