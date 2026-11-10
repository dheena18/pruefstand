"""The run says so when a local judge has no exact tokenizer (T5.2c, D1010)."""

from pathlib import Path

import pytest
from testsupport.gpu_files import SHIPPED_CATALOGUE
from testsupport.pipeline_support import mini_config
from testsupport.runner_support import SpyPool

from pruefstand.core.config import JudgeConfig, ModelRef
from pruefstand.pipeline.judging import exact_count_missing

LOCAL = ModelRef(id="ollama/gemma3:12b", family="gemma")
HOSTED = ModelRef(id="github/openai/gpt-4.1-mini", family="gpt")


@pytest.fixture(autouse=True)
def _catalogue(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRUEFSTAND_GPU_CATALOGUE", str(SHIPPED_CATALOGUE))
    monkeypatch.setenv("PRUEFSTAND_JUDGE_TOKENIZER_DIR", str(tmp_path / "empty"))


def test_a_local_judge_without_the_file_is_reported() -> None:
    cfg = mini_config(judge=JudgeConfig(pr=LOCAL, nightly=LOCAL))
    assert exact_count_missing(SpyPool(), cfg) is True


def test_no_pool_or_a_hosted_judge_has_nothing_to_report() -> None:
    local = mini_config(judge=JudgeConfig(pr=LOCAL, nightly=LOCAL))
    hosted = mini_config(judge=JudgeConfig(pr=HOSTED, nightly=HOSTED))
    assert exact_count_missing(None, local) is False
    assert exact_count_missing(SpyPool(), hosted) is False
