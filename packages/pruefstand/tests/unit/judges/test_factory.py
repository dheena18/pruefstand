"""``build_pool``: one judge per configured model, the run's tier picks the default (S4)."""

from pathlib import Path
from typing import Literal

import pytest
from testsupport.judge_support import NONCE_KEY, configure, make_client
from testsupport.pipeline_support import mini_config

from pruefstand.core.config import JudgeConfig, ModelRef, PruefstandConfig
from pruefstand.judges.factory import DEFAULT_KEY, build_pool
from pruefstand.judges.judge import JudgePool
from pruefstand.llm.client import LLMClient

PR = ModelRef(id="ollama/gemma3:12b", family="gemma")
NIGHT = ModelRef(id="github/openai/gpt-4.1-mini", family="gpt")
OTHER = ModelRef(id="github/meta/llama-3.3-70b-instruct", family="llama")
Tier = Literal["pr", "nightly", "bench"]


def _cfg(**per_metric: ModelRef) -> PruefstandConfig:
    return mini_config(judge=JudgeConfig(pr=PR, nightly=NIGHT, per_metric=per_metric))


def _build(
    cfg: PruefstandConfig, tier: Tier, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[JudgePool, list[str]]:
    configure(tmp_path, monkeypatch, "http://127.0.0.1:9")
    built: list[str] = []

    def make(ref: ModelRef) -> LLMClient:
        built.append(ref.id)
        return make_client()[0]  # a client is only stored here, never called

    return build_pool(cfg, tier=tier, make_client=make, nonce_key=NONCE_KEY), built


@pytest.mark.parametrize(
    ("tier", "expected"), [("pr", PR.id), ("nightly", NIGHT.id), ("bench", PR.id)]
)
def test_the_tier_selects_the_default_judge(
    tier: Tier, expected: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pool, built = _build(_cfg(), tier, tmp_path, monkeypatch)
    assert built == [expected]
    assert pool.for_metric("faithfulness").model == expected


def test_per_metric_overrides_get_their_own_judge_and_each_model_is_built_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = _cfg(faithfulness=OTHER, answer_correctness=OTHER)
    pool, built = _build(cfg, "pr", tmp_path, monkeypatch)
    assert sorted(built) == sorted([PR.id, OTHER.id])
    assert pool.for_metric("faithfulness").model == OTHER.id
    assert pool.for_metric("answer_correctness").model == OTHER.id
    assert pool.for_metric("refusal_judged").model == PR.id
    assert DEFAULT_KEY == "default"
