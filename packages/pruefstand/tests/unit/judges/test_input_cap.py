"""Judge input cap, token estimate, the Judge guard and the answer-echo rule (T5.2b, X3.9)."""

import json
from pathlib import Path

import pytest
from testsupport.gpu_files import SHIPPED_CATALOGUE
from testsupport.judge_support import DE_ROOT, MODEL, configure, make_client, make_judge
from testsupport.judged_support import CAP, judges, user_prompts, verdict
from testsupport.loopback_script import Step, ollama_body

from pruefstand.core.errors import ConfigError, JudgeInputTruncated, LLMError
from pruefstand.judges.judge import CI_NONCE_KEY, Judge
from pruefstand.judges.output import make_task
from pruefstand.judges.tokens import cut_signature, estimate_tokens, input_cap
from pruefstand.llm.prompts import PromptRegistry


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


async def test_a_provider_report_over_the_window_is_a_truncation_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window = 4096 - 77  # num_ctx - num_predict of the loopback catalogue
    body = json.dumps(
        {
            "model": "m",
            "message": {"role": "assistant", "content": '{"reason": "x", "score": 1}'},
            "done": True,
            "prompt_eval_count": window,
            "eval_count": 2,
        }
    ).encode()
    task = make_task("refusal_judged", frage="F?", antwort="A.")
    with (
        judges(tmp_path, monkeypatch, [Step(body=body)]) as (pool, _, _),
        pytest.raises(JudgeInputTruncated),
    ):
        await pool.for_metric("refusal_judged").score(task)


async def test_a_provider_report_below_the_window_is_fine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = make_task("refusal_judged", frage="F?", antwort="A.")
    with judges(tmp_path, monkeypatch, [verdict(1)]) as (pool, _, _):
        assert (await pool.for_metric("refusal_judged").score(task)).raw_score == 1


def env_judge() -> Judge:
    client, _ = make_client()
    return Judge(client, MODEL, PromptRegistry([DE_ROOT]))  # the key comes from the environment


def test_tier_two_refuses_a_weak_or_the_public_ci_nonce_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure(tmp_path, monkeypatch, "http://127.0.0.1:1")
    monkeypatch.setenv("PRUEFSTAND_STACK", "a40")
    for weak in (CI_NONCE_KEY, "abc", "z" * 40, "a" * 31):
        monkeypatch.setenv("PRUEFSTAND_NONCE_KEY", weak)
        with pytest.raises(ConfigError, match="weak or public"):
            env_judge()
    monkeypatch.setenv("PRUEFSTAND_NONCE_KEY", "ab12" * 8)
    env_judge()


def test_tier_one_may_use_the_public_ci_nonce_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure(tmp_path, monkeypatch, "http://127.0.0.1:1")
    monkeypatch.setenv("PRUEFSTAND_STACK", "live")
    monkeypatch.setenv("PRUEFSTAND_NONCE_KEY", CI_NONCE_KEY)
    env_judge()


# Measured on the A40 server (Ollama 0.32.13, 2026-11-09, gemma3:12b, num_ctx 12288, num_predict 1):
# about 1.8 tokens per word gave 910 / 3610 / 7210 / 10810 prompt tokens for 500 / 2000 /
# 4000 / 6000 words, and a constant 6147 for 8 000, 10 000, 14 000, 20 000 and 40 000 words
# (cut): D962.
MEASURED_CUT_REPORT = 6147
MEASURED_UNCUT_REPORTS = (910, 3610, 7210, 10810)


def test_the_cut_signature_of_the_shipped_judge_is_half_the_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRUEFSTAND_GPU_CATALOGUE", str(SHIPPED_CATALOGUE))
    band = cut_signature("ollama/gemma3:12b")
    assert band == (6_144, 6_160)
    assert band[0] <= MEASURED_CUT_REPORT <= band[1]
    assert not any(band[0] <= n <= band[1] for n in MEASURED_UNCUT_REPORTS)
    assert MEASURED_CUT_REPORT < 12_288 - 1_024  # why `reported >= window` alone never sees a cut
    assert cut_signature("github/openai/gpt-4.1-mini") is None


async def test_a_cut_prompt_reported_far_below_the_window_is_a_truncation_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The measured quirk: a cut prompt is reported as about num_ctx / 2 (loopback: 2048)."""
    window = 4096 - 77
    reported = 4096 // 2 + 3  # the +3 measured for the shipped judge
    assert reported < window
    body = json.dumps(
        {
            "model": "m",
            "message": {"role": "assistant", "content": '{"reason": "x", "score": 1}'},
            "done": True,
            "prompt_eval_count": reported,
            "eval_count": 2,
        }
    ).encode()
    task = make_task("refusal_judged", frage="F?", antwort="A.")
    with (
        judges(tmp_path, monkeypatch, [Step(body=body)]) as (pool, _, _),
        pytest.raises(JudgeInputTruncated, match="signature of a cut prompt"),
    ):
        await pool.for_metric("refusal_judged").score(task)


async def test_reports_just_outside_the_cut_band_are_fine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for reported in (4096 // 2 - 1, 4096 // 2 + 17):
        body = json.dumps(
            {
                "model": "m",
                "message": {"role": "assistant", "content": '{"reason": "x", "score": 1}'},
                "done": True,
                "prompt_eval_count": reported,
                "eval_count": 2,
            }
        ).encode()
        task = make_task("refusal_judged", frage="F?", antwort="A.")
        with judges(tmp_path, monkeypatch, [Step(body=body)]) as (pool, _, _):
            assert (await pool.for_metric("refusal_judged").score(task)).raw_score == 1
