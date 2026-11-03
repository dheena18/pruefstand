"""T3.1a CPU tests: ``models.yaml``, ``endpoints.yaml``, ``catalogue_schema.py`` (ADR-0018/0019)."""

import copy
import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from catalogue_schema import (
    DISK_FREE_BUDGET_GB,
    DISK_RESERVE_GB,
    MAX_LOADED_MODELS,
    NUM_PARALLEL,
    VRAM_CARD_BUDGET_GB,
    Catalogue,
    Endpoints,
    disk_total_gb,
    load_catalogue,
    load_endpoints,
    mode_models,
    planned_vram_gb,
)
from gpu_testkit import GEN_DIGEST, GPU_DIR, REPO
from pydantic import ValidationError

from pruefstand.core.models_family import model_family

GEN_ID = "ollama/qwen3.8:27b-q8_0"
JUDGE_ID = "ollama/gemma3:12b"
HEX64 = re.compile(r"^[0-9a-f]{64}$")


@pytest.fixture(scope="module")
def raw() -> dict[str, Any]:
    return yaml.safe_load((GPU_DIR / "models.yaml").read_text(encoding="utf-8"))  # type: ignore[no-any-return]


@pytest.fixture(scope="module")
def cat() -> Catalogue:
    return load_catalogue(GPU_DIR / "models.yaml")


def _mutated(raw: dict[str, Any], model_id: str, **changes: Any) -> dict[str, Any]:
    data = copy.deepcopy(raw)
    for entry in data["models"]:
        if entry["id"] == model_id:
            entry.update(changes)
    return data


def test_models_yaml_parses_and_ollama_ids_are_ollama_slash_tag(cat: Catalogue) -> None:
    assert cat.models
    for e in cat.models:
        if e.engine == "ollama":
            assert e.id == "ollama/" + e.tag
            assert e.digest is not None
            assert HEX64.match(e.digest), e.id


def test_roles_are_exactly_the_four_of_adr_0019(cat: Catalogue) -> None:
    assert {e.role for e in cat.models} == {"generator", "judge", "embed", "rerank"}


@pytest.mark.parametrize("role", ["nightly_judge", "large", "datagen"])
def test_removed_roles_fail(raw: dict[str, Any], role: str) -> None:
    with pytest.raises(ValidationError):
        Catalogue.model_validate(_mutated(raw, JUDGE_ID, role=role))


def test_exactly_one_judge_family_gemma_and_generators_qwen(cat: Catalogue) -> None:
    judges = [e for e in cat.models if e.role == "judge"]
    assert [e.id for e in judges] == [JUDGE_ID]
    assert judges[0].family == "gemma"
    assert model_family(JUDGE_ID) == "gemma"
    for e in cat.models:
        if e.role == "generator":
            assert e.family == "qwen"
            assert model_family(e.id) == "qwen"
        if e.role == "judge":
            assert e.family != "qwen"


def test_a_second_judge_or_a_qwen_judge_fails(raw: dict[str, Any]) -> None:
    second = copy.deepcopy(raw)
    extra = copy.deepcopy(next(e for e in second["models"] if e["id"] == JUDGE_ID))
    extra.update(id="ollama/gemma3:4b", tag="gemma3:4b")
    second["models"].append(extra)
    with pytest.raises(ValidationError):
        Catalogue.model_validate(second)
    with pytest.raises(ValidationError):
        Catalogue.model_validate(_mutated(raw, JUDGE_ID, family="qwen"))


def test_the_generator_entry_is_the_cluster_model(cat: Catalogue) -> None:
    gen = cat.by_id(GEN_ID)
    assert (
        gen.digest
        == GEN_DIGEST
        == "8f5fb6b71ea00052cbe8545738c55ce61112c4e571cb60ca4dad00b131766039"
    )
    assert gen.think is False
    assert gen.quantization == "Q8_0"
    assert "thinking" in gen.capabilities
    assert model_family(GEN_ID) == "qwen"


def test_only_the_cluster_generator_is_standard_and_protected(raw: dict[str, Any]) -> None:
    """``fetch-model.sh --rm`` protects the standard generator (D451, D630)."""
    protected = [
        m["id"] for m in raw["models"] if m.get("role") == "generator" and m.get("standard")
    ]
    assert protected == [GEN_ID]


def test_every_entry_with_the_thinking_capability_has_think_false(raw: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Catalogue.model_validate(_mutated(raw, GEN_ID, think=None))
    with pytest.raises(ValidationError):
        Catalogue.model_validate(_mutated(raw, GEN_ID, think=True))


def test_disk_total_of_the_standard_set_leaves_the_reserve(cat: Catalogue) -> None:
    pulled = disk_total_gb(cat, include_generator=False)
    assert pulled > 9  # bge-m3 + gemma3:12b
    assert DISK_FREE_BUDGET_GB - pulled >= DISK_RESERVE_GB


def test_a_standard_set_that_does_not_fit_fails(raw: dict[str, Any]) -> None:
    huge = _mutated(raw, JUDGE_ID, disk_bytes=13_000_000_000)
    with pytest.raises(ValidationError):
        Catalogue.model_validate(huge)


@pytest.mark.parametrize("licence", ["CC-BY-NC-4.0", "research-only", "unknown"])
def test_licences_outside_the_allowlist_fail(raw: dict[str, Any], licence: str) -> None:
    with pytest.raises(ValidationError):
        Catalogue.model_validate(_mutated(raw, JUDGE_ID, license=licence))


@pytest.mark.parametrize("key", ["num_ctx", "num_predict", "temperature", "seed", "top_p"])
def test_every_chat_and_embed_entry_needs_all_five_options(raw: dict[str, Any], key: str) -> None:
    for model_id in (GEN_ID, "ollama/bge-m3"):
        options = {
            k: v
            for k, v in next(e for e in raw["models"] if e["id"] == model_id)["options"].items()
            if k != key
        }
        with pytest.raises(ValidationError):
            Catalogue.model_validate(_mutated(raw, model_id, options=options))


def test_judge_num_predict_is_at_most_384(cat: Catalogue, raw: dict[str, Any]) -> None:
    assert cat.by_id(JUDGE_ID).options.num_predict <= 384  # type: ignore[union-attr]
    entry = next(e for e in raw["models"] if e["id"] == JUDGE_ID)
    with pytest.raises(ValidationError):
        Catalogue.model_validate(
            _mutated(raw, JUDGE_ID, options={**entry["options"], "num_predict": 385})
        )


def test_judge_context_is_generator_context_plus_4096(cat: Catalogue, raw: dict[str, Any]) -> None:
    gen, judge = cat.by_id(GEN_ID), cat.by_id(JUDGE_ID)
    assert gen.options.num_ctx == 8192  # type: ignore[union-attr]
    assert judge.options.num_ctx >= gen.options.num_ctx + 4096  # type: ignore[union-attr]
    entry = next(e for e in raw["models"] if e["id"] == JUDGE_ID)
    with pytest.raises(ValidationError):
        Catalogue.model_validate(
            _mutated(raw, JUDGE_ID, options={**entry["options"], "num_ctx": 8192})
        )


def test_chat_entries_have_bounds_that_contain_their_defaults(
    cat: Catalogue, raw: dict[str, Any]
) -> None:
    for e in cat.models:
        if e.role in {"generator", "judge"}:
            assert e.option_bounds is not None
            assert e.options is not None
            low, high = e.option_bounds.temperature
            assert low <= e.options.temperature <= high
    entry = next(e for e in raw["models"] if e["id"] == GEN_ID)
    bad = {**entry["option_bounds"], "temperature": [0.5, 1.0]}  # default 0 is outside
    with pytest.raises(ValidationError):
        Catalogue.model_validate(_mutated(raw, GEN_ID, option_bounds=bad))
    with pytest.raises(ValidationError):
        Catalogue.model_validate(_mutated(raw, GEN_ID, option_bounds=None))


def test_chat_entries_carry_a_tokenizer_with_a_64_hex_sha256(
    cat: Catalogue, raw: dict[str, Any]
) -> None:
    for e in cat.models:
        if e.role in {"generator", "judge"}:
            assert e.tokenizer is not None
            assert e.tokenizer.source
            assert HEX64.match(e.tokenizer.sha256)
    with pytest.raises(ValidationError):
        Catalogue.model_validate(
            _mutated(raw, GEN_ID, tokenizer={"source": "hf:x", "sha256": "abc"})
        )


def test_embed_context_equals_max_input_tokens(cat: Catalogue, raw: dict[str, Any]) -> None:
    for e in cat.models:
        if e.role == "embed":
            assert e.options.num_ctx == e.max_input_tokens  # type: ignore[union-attr]
    entry = next(e for e in raw["models"] if e["id"] == "ollama/bge-m3")
    with pytest.raises(ValidationError):
        Catalogue.model_validate(
            _mutated(raw, "ollama/bge-m3", options={**entry["options"], "num_ctx": 8192})
        )


def test_planned_vram_per_card_fits_in_every_mode(cat: Catalogue) -> None:
    for mode in ("day", "night"):
        cards = planned_vram_gb(cat, mode)
        assert set(cards) == {"generator", "judge"}
        assert all(0 < gb <= VRAM_CARD_BUDGET_GB for gb in cards.values()), cards
        assert len(mode_models(cat, mode)) <= MAX_LOADED_MODELS == 3
    assert NUM_PARALLEL == 4


def test_day_and_night_load_the_same_models_generator_first(cat: Catalogue) -> None:
    day = [e.id for e in mode_models(cat, "day")]
    assert day == [e.id for e in mode_models(cat, "night")]
    assert day == [GEN_ID, "ollama/bge-m3", JUDGE_ID]
    with pytest.raises(ValueError, match="datagen"):
        mode_models(cat, "datagen")


def test_a_generator_that_does_not_fit_one_card_fails(raw: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Catalogue.model_validate(_mutated(raw, GEN_ID, kv_bytes_per_token=5_000_000))


def test_endpoints_point_at_catalogue_ids_and_the_three_url_settings(cat: Catalogue) -> None:
    ep = load_endpoints(GPU_DIR / "endpoints.yaml", cat)
    assert ep.endpoints
    ids = {e.id for e in cat.models}
    for name, e in ep.endpoints.items():
        assert e.model_id in ids, name
        assert e.base_url_env in {"OLLAMA_GPU0_URL", "OLLAMA_GPU1_URL", "RERANK_URL"}
        assert e.kind in {"chat", "embed", "rerank"}
    assert {e.model_id for e in ep.endpoints.values()} >= {GEN_ID, JUDGE_ID, "ollama/bge-m3"}


def test_an_endpoint_with_an_unknown_model_or_url_setting_fails(cat: Catalogue) -> None:
    good = yaml.safe_load((GPU_DIR / "endpoints.yaml").read_text(encoding="utf-8"))
    name = next(iter(good["endpoints"]))
    for field, value in (("model_id", "ollama/nope:1b"), ("base_url_env", "OLLAMA_GPU2_URL")):
        bad = copy.deepcopy(good)
        bad["endpoints"][name][field] = value
        with pytest.raises((ValidationError, ValueError)):
            Endpoints.model_validate(bad).check_against(cat)


def test_no_host_names_ips_or_keys_in_the_yaml_files() -> None:
    for name in ("models.yaml", "endpoints.yaml"):
        text = (GPU_DIR / name).read_text(encoding="utf-8")
        assert not re.search(r"\b\d{1,3}(\.\d{1,3}){3}\b", text), name
        assert not re.search(r"https?://", text.replace("https://huggingface.co", "")), name
        assert not re.search(r"(?i)api[_-]?key|(?<![_a-z])token\s*:|password|secret", text), name


def test_the_committed_files_sit_where_the_package_setting_expects(tmp_path: Path) -> None:
    assert (REPO / "infra" / "gpu" / "models.yaml").is_file()
    assert (REPO / "infra" / "gpu" / "endpoints.yaml").is_file()
    assert tmp_path.exists()


def test_the_reranker_entry_carries_the_passage_limit_and_a_cpu_sized_timeout(
    cat: Catalogue,
) -> None:
    """T3.5: rag-demo reads both from the catalogue instead of hard-coding them (D222)."""
    entry = next(e for e in cat.models if e.role == "rerank")
    assert entry.max_input_tokens == 256
    assert entry.request_timeout_s is not None
    assert 10 <= entry.request_timeout_s <= 300
