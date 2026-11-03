"""``complete_json`` over a scripted loopback server: prose, repair, umlauts."""

import json

import pytest
from pydantic import BaseModel
from testsupport.llm_scenarios import echo_request
from testsupport.loopback import completion_json
from testsupport.loopback_script import Step, serve_script

from pruefstand.core.config import LLMPolicyConfig
from pruefstand.core.errors import LLMError
from pruefstand.core.models.llm import LLMRequest
from pruefstand.llm.backends.litellm import LiteLLMBackend
from pruefstand.llm.budget import Budget
from pruefstand.llm.client import LLMClient
from pruefstand.llm.policy import LLMPolicy
from pruefstand.llm.recorder import CallRecorder

MODEL = "openai_compatible_local/m"


class Verdict(BaseModel):
    reason: str
    score: int


def _body(text: str) -> Step:
    return Step(body=completion_json(text))


def _client(base: str) -> LLMClient:
    backend = LiteLLMBackend(MODEL, api_base=f"{base}/v1", api_key_env=None, timeout_s=30)
    return LLMClient(
        backend, None, Budget(None, None), CallRecorder(), LLMPolicy(LLMPolicyConfig())
    )


def _req() -> LLMRequest:
    return echo_request().model_copy(update={"model": MODEL})


async def test_prose_before_the_object_is_skipped_and_umlauts_survive() -> None:
    text = 'Begründung: Die Kündigung ist wirksam. {"reason": "Fristgerecht gekündigt", "score": 2}'
    with serve_script([_body(text)]) as (base, state):
        result = await _client(base).complete_json(_req(), Verdict)
    assert result == Verdict(reason="Fristgerecht gekündigt", score=2)
    assert state.posts() == 1
    assert state.seen[-1].body["response_format"] == {"type": "json_object"}


async def test_invalid_then_valid_needs_two_calls() -> None:
    steps = [_body("kein JSON"), _body(json.dumps({"reason": "ok", "score": 1}))]
    with serve_script(steps) as (base, state):
        result = await _client(base).complete_json(_req(), Verdict)
    assert result.score == 1
    assert state.posts() == 2


async def test_invalid_twice_is_an_llm_error() -> None:
    steps = [_body("nein"), _body('{"reason": 3}')]
    with serve_script(steps) as (base, state), pytest.raises(LLMError, match="invalid JSON"):
        await _client(base).complete_json(_req(), Verdict)
    assert state.posts() == 2
