"""The judge family rule at config load and at run time (S6, W3.1, ADR-0019)."""

import pytest

from pruefstand.core.config import JudgeConfig, ModelRef
from pruefstand.core.errors import ConfigError
from pruefstand.core.models.target import TargetInfo
from pruefstand.judges.family_guard import check_judge_families

GEMMA = ModelRef(id="ollama/gemma3:12b", family="gemma")
QWEN_JUDGE = ModelRef(id="ollama/qwen3:4b", family="qwen")
GPT = ModelRef(id="github/openai/gpt-4.1-mini", family="gpt")


def _info(generator: str) -> TargetInfo:
    return TargetInfo(
        app_version="1",
        git_sha="a" * 40,
        image_digest=None,
        config_hash="h",
        corpus_version="c",
        models={"generator": generator},
    )


def test_a_gemma_judge_against_a_qwen_generator_is_fine() -> None:
    cfg = JudgeConfig(pr=GEMMA, nightly=GEMMA)
    check_judge_families(cfg, [_info("qwen3.8:27b-q8_0")])
    check_judge_families(cfg, [_info("ollama/qwen3.8:27b-q8_0"), _info("qwen3.8:27b-q8_0")])


def test_the_tier1_github_judge_against_qwen_is_fine() -> None:
    cfg = JudgeConfig(pr=GPT, nightly=GPT)
    check_judge_families(cfg, [_info("qwen3.8:27b-q8_0")])


def test_a_judge_of_the_candidates_generator_family_is_refused() -> None:
    cfg = JudgeConfig(pr=QWEN_JUDGE, nightly=QWEN_JUDGE)
    with pytest.raises(ConfigError, match="qwen"):
        check_judge_families(cfg, [_info("llama3.3:70b"), _info("qwen3.8:27b-q8_0")])


def test_only_the_clashing_run_is_named_and_baseline_alone_may_pass() -> None:
    cfg = JudgeConfig(pr=GEMMA, nightly=GEMMA)
    check_judge_families(cfg, [_info("qwen3.8:27b-q8_0")])
    with pytest.raises(ConfigError, match="gemma"):
        check_judge_families(cfg, [_info("qwen3.8:27b-q8_0"), _info("gemma3:4b")])


def test_a_per_metric_override_is_checked_too() -> None:
    cfg = JudgeConfig(pr=GEMMA, nightly=GEMMA, per_metric={"faithfulness": QWEN_JUDGE})
    with pytest.raises(ConfigError, match=r"faithfulness|qwen"):
        check_judge_families(cfg, [_info("qwen3.8:27b-q8_0")])


def test_an_unknown_generator_id_is_a_config_error() -> None:
    cfg = JudgeConfig(pr=GEMMA, nightly=GEMMA)
    with pytest.raises(ConfigError, match="zorglub"):
        check_judge_families(cfg, [_info("zorglub-9b")])


def test_an_unknown_judge_id_is_a_config_error() -> None:
    cfg = JudgeConfig(pr=ModelRef(id="ollama/zorglub:1b", family="gemma"), nightly=GEMMA)
    with pytest.raises(ConfigError, match="zorglub"):
        check_judge_families(cfg, [_info("qwen3.8:27b-q8_0")])


def test_a_target_without_a_reported_generator_is_a_config_error() -> None:
    cfg = JudgeConfig(pr=GEMMA, nightly=GEMMA)
    info = _info("x").model_copy(update={"models": {}})
    with pytest.raises(ConfigError, match="generator"):
        check_judge_families(cfg, [info])
