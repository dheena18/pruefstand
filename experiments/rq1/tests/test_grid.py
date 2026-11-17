"""T7.3 S1/S2 (pure parts): grid expander, rq1 cases, correctness subsample, night window."""

from datetime import UTC, datetime
from typing import Any

import pytest
import yaml
from rq1.grid import GRID, apply_overrides, expand, overrides_hash
from rq1.plan import (
    check_dispatch_time,
    correctness_subsample,
    request_plan,
    rq1_cases,
)
from rq1.volume import take_until_budget

from pruefstand.core.errors import ConfigError
from pruefstand.core.models.testcase import TestCase
from rag_demo.models import RagConfig

REPO = GRID.parents[2]
BASE = yaml.safe_load((REPO / "apps/rag-demo/configs/rag.gpu.yaml").read_text(encoding="utf-8"))
INSTRUCT = (
    "Instruct: Given a German legal question, retrieve the statute passage that answers it\nQuery: "
)


def test_12_effective_configs_and_18_with_the_extended_embedder() -> None:
    configs = expand()
    assert len(configs) == 12
    assert len(expand(extended=True)) == 18
    dense = [c for c in configs if c.retrieval == "dense"]
    assert all(c.compound_split is None and "analyzer" not in c.overrides for c in dense)
    assert len({c.name for c in configs}) == len({c.config_hash for c in configs}) == 12


def test_config_hashes_are_stable() -> None:
    assert [c.config_hash for c in expand()] == [c.config_hash for c in expand()]
    first = expand()[0]
    assert first.config_hash == overrides_hash(first.overrides)


@pytest.mark.parametrize("config", expand(extended=True), ids=lambda c: c.name)
def test_every_config_is_a_valid_ragconfig(config: Any) -> None:
    cfg = RagConfig.model_validate(apply_overrides(BASE, config.overrides))
    assert cfg.retrieval.hybrid is (config.retrieval == "hybrid")
    if config.chunking == "fixed_512":
        assert (cfg.chunking.strategy, cfg.chunking.size) == ("fixed_tokens", 512)


def test_e5_uses_the_instruct_prefixes_on_the_vm_cpu_and_bge_m3_none() -> None:
    for config in expand():
        embed = RagConfig.model_validate(apply_overrides(BASE, config.overrides)).embed
        if config.embedder == "e5_large_instruct":
            assert (embed.engine, embed.query_prefix, embed.doc_prefix) == ("tei", INSTRUCT, "")
            assert embed.max_input_tokens == 512
            assert embed.catalogue_id is None  # never an Ollama model on the cluster (D1263)
        else:
            assert (embed.query_prefix, embed.doc_prefix) == ("", "")
            assert embed.catalogue_id is not None
            assert embed.catalogue_id.startswith("ollama/")


def _case(case_id: str, base: str, split: str, perturbation: str | None = None) -> TestCase:
    return TestCase.model_validate(
        {
            "id": case_id,
            "base_id": base,
            "cluster_id": base,
            "tenant": "shared_public",
            "lang": "de",
            "question": "Wie lang ist die Kündigungsfrist?",
            "reference_answer": "Vier Wochen.",
            "category": "factual",
            "difficulty": "easy",
            "split": split,
            "perturbation": perturbation,
            "source": "generated+reviewed",
            "license_config": "laws_eurlex",
            "corpus_version": "v1",
        }
    )


def test_the_case_loader_keeps_rq1_and_never_full() -> None:
    cases = [_case("a", "a", "rq1"), _case("b", "b", "full"), _case("c", "c", "core")]
    assert [c.id for c in rq1_cases(cases)] == ["a"]


def test_the_subsample_is_a_seeded_subset_of_the_rq1_bases() -> None:
    bases = [f"b{i:03d}" for i in range(300)]
    first = correctness_subsample(bases, 60)
    assert first == correctness_subsample(list(reversed(bases)), 60)
    assert len(first) == 60
    assert set(first) <= set(bases)
    assert first != correctness_subsample(bases, 60, seed=1235)
    with pytest.raises(ConfigError, match="subsample size"):
        correctness_subsample(bases, 301)


def test_query_only_for_the_subsample_retrieve_for_every_other_case() -> None:
    cases = [
        _case("b1", "b1", "rq1"),
        _case("b1-typos", "b1", "rq1", "typos"),
        _case("b2", "b2", "rq1"),
    ]
    assert request_plan(cases, ["b1"]) == {"b1": "query", "b1-typos": "query", "b2": "retrieve"}


def test_equal_volume_for_per_paragraph_and_512_token_chunks() -> None:
    assert take_until_budget([1800] * 3) == (1800, 1800, 496)
    assert len(take_until_budget([512] * 10)) == 8


@pytest.mark.parametrize(
    ("utc_hour", "verdict"),
    [(22, "refused"), (4, "refused"), (5, "ok"), (12, "ok"), (20, "ok"), (21, "refused")],
)
def test_the_night_window_refuses_a_dispatch(utc_hour: int, verdict: str) -> None:
    now = datetime(2026, 11, 16, utc_hour, 0, tzinfo=UTC)  # Berlin = UTC+1 in November
    if verdict == "refused":
        with pytest.raises(ConfigError, match="night window"):
            check_dispatch_time(now)
    else:
        check_dispatch_time(now)
    with pytest.raises(ConfigError, match="timezone-aware"):
        check_dispatch_time(datetime(2026, 11, 16, 23, 0))  # noqa: DTZ001
