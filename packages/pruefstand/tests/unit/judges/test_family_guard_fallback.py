"""The fallback judge joins the run-time family check (T5.2b follow-up of T5.2a)."""

import pytest

from pruefstand.core.config import JudgeConfig, ModelRef
from pruefstand.core.errors import ConfigError
from pruefstand.core.models.target import TargetInfo
from pruefstand.judges.family_guard import check_judge_families

GEMMA = ModelRef(id="ollama/gemma3:12b", family="gemma")
QWEN = ModelRef(id="ollama/qwen3:4b", family="qwen")


def info(generator: str) -> TargetInfo:
    return TargetInfo(
        app_version="1",
        git_sha="a" * 40,
        image_digest=None,
        config_hash="h",
        corpus_version="c",
        models={"generator": generator},
    )


def test_a_fallback_judge_of_the_generator_family_is_refused() -> None:
    cfg = JudgeConfig(pr=GEMMA, nightly=GEMMA)
    with pytest.raises(ConfigError, match=r"llm\.fallback_judge"):
        check_judge_families(cfg, [info("qwen3.8:27b-q8_0")], QWEN)


def test_a_fallback_judge_of_another_family_is_fine() -> None:
    cfg = JudgeConfig(pr=GEMMA, nightly=GEMMA)
    check_judge_families(cfg, [info("llama3.3:70b")], QWEN)
    check_judge_families(cfg, [info("qwen3.8:27b-q8_0")], None)
