"""T6.3 S1: no-op and churn variants of rag.gpu.yaml and the run plan of a noise arm."""

import json
from collections.abc import Mapping
from pathlib import Path

import numpy as np
import pytest
import yaml
from noise.noop import (
    GPU_CONFIG,
    REPO,
    CacheMode,
    Mode,
    PlannedRun,
    build_plan,
    churn_overrides,
    load_base,
    reorder,
)
from noise.run_noise import main

from pruefstand.core.errors import ConfigError
from rag_demo.config import config_hash, parse_config

CATALOGUE = REPO / "infra/gpu/models.yaml"


def rag_hash(config: Mapping[str, object]) -> str:
    text = yaml.safe_dump(config, sort_keys=False, allow_unicode=True)
    return config_hash(parse_config(text, CATALOGUE))


def generation(run: PlannedRun) -> Mapping[str, object]:
    section = run.config["generation"]
    assert isinstance(section, dict)
    return section


def keys(config: object) -> list[object]:
    if not isinstance(config, dict):
        return []
    return [(k, keys(v)) for k, v in config.items()]


def test_reorder_keeps_values_changes_order_and_keeps_the_config_hash() -> None:
    base = load_base()
    permuted = reorder(base, np.random.default_rng(1234))
    assert permuted == base
    assert keys(permuted) != keys(base)
    assert rag_hash(permuted) == config_hash(parse_config(GPU_CONFIG.read_text("utf-8"), CATALOGUE))


def test_the_same_seed_gives_the_same_permutation() -> None:
    base = load_base()
    first = keys(reorder(base, np.random.default_rng(7)))
    assert first == keys(reorder(base, np.random.default_rng(7)))
    assert first != keys(reorder(base, np.random.default_rng(8)))


@pytest.mark.parametrize("kind", ["reindex", "reorder", "rebuild"])
def test_a_noop_plan_always_regenerates(kind: str) -> None:
    runs = build_plan("noop", kind, repeats=2, cache_mode="production", seed=1234)
    assert [r.label for r in runs] == ["main", f"noop-{kind}-1", f"noop-{kind}-2"]
    assert all(r.target_cache == "off" and r.judge_cache == "production" for r in runs)
    assert all(r.rebuild_index for r in runs)
    seeds = [generation(r)["seed"] for r in runs]
    assert seeds == [1234, 1235, 1236]
    assert [r.rebuild_image for r in runs] == [False, kind == "rebuild", kind == "rebuild"]
    assert len({r.collection for r in runs}) == len(runs)


def test_temp03_reaches_the_generator_with_a_seed_per_run() -> None:
    runs = build_plan("churn", "temp03", repeats=3, cache_mode="production", seed=1234)
    sections = [generation(r) for r in runs]
    assert [g["temperature"] for g in sections] == [0.0, 0.3, 0.3, 0.3]
    assert len({g["seed"] for g in sections}) == 4
    assert rag_hash(runs[1].config) != rag_hash(load_base())
    assert not any(r.rebuild_index for r in runs)


def test_prompt_synonym_is_mutation_n04_and_quant_swap_waits_for_n09() -> None:
    assert churn_overrides("prompt_synonym") == ({}, "N04")
    runs = build_plan("churn", "prompt_synonym", repeats=1, cache_mode="production", seed=1)
    assert [r.mutation for r in runs] == [None, "N04"]
    with pytest.raises(ConfigError, match="N09 is pending"):
        build_plan("churn", "quant_swap", repeats=1, cache_mode="production", seed=1)


@pytest.mark.parametrize("cache_mode", ["production", "off"])
def test_repeats_are_the_unchanged_config_with_the_chosen_caches(cache_mode: CacheMode) -> None:
    runs = build_plan("repeats", None, repeats=5, cache_mode=cache_mode, seed=1234)
    assert len(runs) == 6
    assert all(r.config == load_base() for r in runs)
    assert {(r.target_cache, r.judge_cache) for r in runs} == {(cache_mode, cache_mode)}
    assert not any(r.rebuild_index or r.rebuild_image or r.mutation for r in runs)


@pytest.mark.parametrize(
    ("mode", "kind", "repeats", "cache_mode", "match"),
    [
        ("noop", None, 2, "production", "needs a kind"),
        ("noop", "temp03", 2, "production", "needs a kind"),
        ("repeats", "reindex", 2, "production", "takes no kind"),
        ("noop", "reindex", 0, "production", "repeats must be"),
        ("churn", "temp03", 2, "off", "always regenerates"),
    ],
)
def test_wrong_combinations_are_refused(
    mode: Mode, kind: str | None, repeats: int, cache_mode: CacheMode, match: str
) -> None:
    with pytest.raises(ConfigError, match=match):
        build_plan(mode, kind, repeats=repeats, cache_mode=cache_mode, seed=1)


def test_the_cli_writes_the_plan_and_one_config_per_run(tmp_path: Path) -> None:
    argv = ["--mode", "noop", "--noop-kind", "reorder", "--repeats", "2", "--out", str(tmp_path)]
    assert main(argv) == 0
    arm = tmp_path / "noop_reorder"
    plan = json.loads((arm / "plan.json").read_text(encoding="utf-8"))
    assert [row["label"] for row in plan] == ["main", "noop-reorder-1", "noop-reorder-2"]
    for row in plan:
        config = yaml.safe_load((arm / f"rag.{row['label']}.yaml").read_text(encoding="utf-8"))
        assert rag_hash(config) != ""  # every written config parses against the catalogue
    assert main([*argv[:4], "--churn-kind", "temp03", "--out", str(tmp_path)]) == 2
