"""plan() on the real catalogue and main's real rag.gpu.yaml (X3.15, D221, AI12-08)."""

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml
from gate_orchestrator.models import Job
from gate_orchestrator.plan import collection_name, plan

ROOT = Path(__file__).resolve().parents[4]
CATALOGUE: dict[str, Any] = yaml.safe_load((ROOT / "infra/gpu/models.yaml").read_text("utf-8"))
MAIN: dict[str, Any] = yaml.safe_load(
    (ROOT / "apps/rag-demo/configs/rag.gpu.yaml").read_text("utf-8")
)
PR_JOB = Job(kind="gate", sha="f" * 40, pr_number=5, tier="pr")


def _pr(**changes: Any) -> dict[str, Any]:
    cfg = copy.deepcopy(MAIN)
    for dotted, value in changes.items():
        section, key = dotted.split("__")
        cfg[section][key] = value
    return cfg


def test_main_profile_on_a_pr_is_shared_index_overlay_cache() -> None:
    p = plan(PR_JOB, _pr(), CATALOGUE, main_rag_yaml=MAIN)
    assert (p.generator, p.embedder) == ("ollama/qwen3.8:27b-q8_0", "ollama/bge-m3")
    assert (p.index_mode, p.cache_mode, p.status_hint) == ("shared", "overlay", "ok")


def test_other_catalogue_generator_is_used() -> None:
    p = plan(PR_JOB, _pr(generator__catalogue_id="ollama/qwen3:4b"), CATALOGUE, main_rag_yaml=MAIN)
    assert p.generator == "ollama/qwen3:4b"
    assert p.status_hint == "ok"
    assert p.index_mode == "shared"


@pytest.mark.parametrize(
    "change",
    [
        {"generator__catalogue_id": "ollama/llama3:70b"},
        {"generator__catalogue_id": "ollama/gemma3:12b"},  # a judge is not a generator
        {"embed__catalogue_id": "ollama/qwen3.8:27b-q8_0"},
        {"generator__catalogue_id": "openai/gpt-4o"},
    ],
)
def test_non_catalogue_or_wrong_role_is_unsupported(change: dict[str, str]) -> None:
    p = plan(PR_JOB, _pr(**change), CATALOGUE, main_rag_yaml=MAIN)
    assert p.status_hint == "unsupported_config"
    assert p.generator == "ollama/qwen3.8:27b-q8_0"


@pytest.mark.parametrize(
    "change",
    [{"embed__doc_prefix": "passage: "}, {"embed__max_input_tokens": 512}, {"embed__dim": 768}],
)
def test_embedding_change_needs_a_pr_scoped_index(change: dict[str, Any]) -> None:
    assert plan(PR_JOB, _pr(**change), CATALOGUE, main_rag_yaml=MAIN).index_mode == "pr_scoped"


@pytest.mark.parametrize("tier", ["main", "nightly", "release"])
def test_trusted_tiers_use_the_shared_cache(tier: str) -> None:
    job = Job(kind="gate", sha="f" * 40, pr_number=None, tier=tier)  # type: ignore[arg-type]  # parametrised Literal
    assert plan(job, MAIN, CATALOGUE, main_rag_yaml=MAIN).cache_mode == "shared"


def test_generation_only_change_keeps_the_shared_index() -> None:
    cfg = copy.deepcopy(MAIN)
    cfg["generation"]["temperature"] = 0.3
    cfg["top_k"] = 4
    assert plan(PR_JOB, cfg, CATALOGUE, main_rag_yaml=MAIN).index_mode == "shared"


def test_broken_main_profile_is_an_error() -> None:
    with pytest.raises(ValueError, match="main"):
        plan(PR_JOB, MAIN, CATALOGUE, main_rag_yaml=_pr(generator__catalogue_id="ollama/x"))


def test_collection_name() -> None:
    assert collection_name(42, "1a2b3c4" + "d" * 33) == "pr_42_1a2b3c4"
