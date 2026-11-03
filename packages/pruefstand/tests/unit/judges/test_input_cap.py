"""Judge input cap, token estimate, the Judge guard and the answer-echo rule (T5.2b, X3.9)."""

from pathlib import Path

import pytest
from testsupport.gpu_files import SHIPPED_CATALOGUE
from testsupport.judge_support import configure, make_judge
from testsupport.judged_support import CAP, judges, user_prompts
from testsupport.loopback_script import Step, ollama_body

from pruefstand.core.errors import ConfigError, LLMError
from pruefstand.judges.output import make_task
from pruefstand.judges.tokens import estimate_tokens, input_cap


def test_the_a40_judge_cap_is_its_window_minus_1024(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRUEFSTAND_GPU_CATALOGUE", str(SHIPPED_CATALOGUE))
    assert input_cap("ollama/gemma3:12b") == 12_288 - 1_024 == 11_264


def test_the_github_judge_cap_is_its_documented_input_limit_minus_1024() -> None:
    assert input_cap("github/openai/gpt-4.1-mini") == 8_000 - 1_024


def test_another_provider_gets_the_default_window() -> None:
    assert input_cap("openai_compatible_local/x") == 8_192 - 1_024


def test_an_ollama_judge_the_catalogue_does_not_list_is_a_config_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRUEFSTAND_GPU_CATALOGUE", str(SHIPPED_CATALOGUE))
    with pytest.raises(ConfigError, match="catalogue"):
        input_cap("ollama/not-in-the-catalogue:1b")


def test_the_estimate_never_undercounts_german_text() -> None:
    text = "Die Kündigungsfrist für Arbeitnehmer beträgt grundsätzlich vier Wochen. " * 50
    assert estimate_tokens(text) >= len(text.split()) * 2  # a real tokenizer needs >= 2 per word


async def test_the_judge_refuses_a_prompt_over_its_cap_without_a_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = make_task("refusal_judged", frage="Frage?", antwort="Wort. " * 5000)
    with judges(tmp_path, monkeypatch, [Step(body=ollama_body("{}"))]) as (pool, state, _):
        judge = pool.for_metric("refusal_judged")
        assert judge.input_cap == CAP
        assert judge.prompt_tokens(task) > CAP
        with pytest.raises(LLMError, match="input cap"):
            await judge.score(task)
    assert user_prompts(state) == []  # never a silent cut by Ollama: nothing is sent


def test_a_judge_builds_without_reading_the_catalogue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure(tmp_path, monkeypatch, "http://127.0.0.1:1")
    judge, _ = make_judge()
    assert judge.model.startswith("ollama/")  # the cap is read on first use (D520)
