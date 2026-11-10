"""A fallback judge answer skips only the exact comparison, end to end through ``score`` (T5.2c)."""

import json
from pathlib import Path

import pytest
from testsupport.exact_support import NUM_CTX, WINDOW, grow, install_tokenizer, make_probe
from testsupport.judge_support import DE_ROOT, MODEL, NONCE_KEY
from testsupport.loopback_script import Step, serve_script

from pruefstand.core.config import LLMPolicyConfig
from pruefstand.core.errors import JudgeInputTruncated, QuotaExhausted
from pruefstand.core.models.llm import LLMRequest, LLMResponse
from pruefstand.judges.judge import Judge
from pruefstand.llm.backends.litellm import LiteLLMBackend
from pruefstand.llm.budget import Budget
from pruefstand.llm.client import LLMClient
from pruefstand.llm.policy import LLMPolicy
from pruefstand.llm.prompts import PromptRegistry
from pruefstand.llm.recorder import CallRecorder

FALLBACK = "openai_compatible_local/fb"


class OutOfQuota:
    """The primary backend: its free quota is used up (the real exception the client reacts to)."""

    async def acomplete(self, req: LLMRequest) -> LLMResponse:
        message = "quota used up"
        raise QuotaExhausted(message, status=429)


def completion(reported: int) -> bytes:
    body = {
        "id": "chatcmpl-loop",
        "object": "chat.completion",
        "model": "fb",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": '{"reason": "x", "score": 1}'},
            }
        ],
        "usage": {"prompt_tokens": reported, "completion_tokens": 2, "total_tokens": reported + 2},
    }
    return json.dumps(body).encode()


async def score_via_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reported: int):  # type: ignore[no-untyped-def]
    """Score a window-filling prompt; the fallback judge answers with ``reported`` tokens."""
    install_tokenizer(tmp_path, monkeypatch, present=True)
    probe, _ = make_probe(tmp_path, monkeypatch)
    task, exact, _ = grow(probe, 1.0)
    assert exact >= WINDOW
    assert probe.prompt_tokens(task) <= probe.input_cap  # the estimate lets it through
    with serve_script([Step(body=completion(reported))]) as (origin, _):
        fallback = LiteLLMBackend(FALLBACK, f"{origin}/v1", None, 30)
        client = LLMClient(
            OutOfQuota(),
            None,
            Budget(None, None),
            CallRecorder(),
            LLMPolicy(LLMPolicyConfig()),
            fallback=fallback,
        )
        judge = Judge(client, MODEL, PromptRegistry([DE_ROOT]), nonce_key=NONCE_KEY)
        return await judge.score(task)


async def test_the_exact_comparison_is_skipped_for_a_fallback_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    verdict = await score_via_fallback(tmp_path, monkeypatch, 3_000)  # (a) and (b) do not hold
    assert verdict.judge_model == FALLBACK
    assert verdict.raw_score == 1


async def test_the_window_and_the_band_still_apply_to_a_fallback_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(JudgeInputTruncated, match="window leaves"):
        await score_via_fallback(tmp_path / "a", monkeypatch, WINDOW)
    with pytest.raises(JudgeInputTruncated, match="signature of a cut prompt"):
        await score_via_fallback(tmp_path / "b", monkeypatch, NUM_CTX // 2 + 3)
