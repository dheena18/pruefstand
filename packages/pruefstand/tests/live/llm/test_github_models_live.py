"""Real GitHub Models call (free tier): a German JSON judgment validates (D333)."""

import os

import pytest
from pydantic import BaseModel
from testsupport.llm_scenarios import SENTENCE

from pruefstand.core.config import LLMPolicyConfig
from pruefstand.core.models.llm import LLMRequest, LLMRole, Message
from pruefstand.llm.backends.litellm import LiteLLMBackend
from pruefstand.llm.budget import Budget
from pruefstand.llm.client import LLMClient
from pruefstand.llm.policy import LLMPolicy
from pruefstand.llm.recorder import CallRecorder

pytestmark = [pytest.mark.live, pytest.mark.network]
MODEL = os.environ.get("PRUEFSTAND_GH_MODELS_TEST_MODEL", "github/openai/gpt-4.1-mini")


class Judgment(BaseModel):
    reason: str
    score: int


@pytest.mark.skipif(
    not os.environ.get("PRUEFSTAND_GH_MODELS_TOKEN"),
    reason="PRUEFSTAND_GH_MODELS_TOKEN is not set (fork PRs and offline runs have no token)",
)
async def test_a_german_json_judgment_validates() -> None:
    backend = LiteLLMBackend(
        MODEL,
        api_base="https://models.github.ai/inference",
        api_key_env="PRUEFSTAND_GH_MODELS_TOKEN",
        timeout_s=60,
    )
    recorder = CallRecorder()
    client = LLMClient(
        backend, None, Budget(0.0, None, max_requests=4), recorder, LLMPolicy(LLMPolicyConfig())
    )
    prompt = (
        f'Bewerte den Satz auf einer Skala von 1 bis 5: "{SENTENCE}" '
        'Antworte nur mit JSON: {"reason": "<kurze Begründung>", "score": <Zahl>}.'
    )
    request = LLMRequest(
        role=LLMRole.JUDGE,
        model=MODEL,
        messages=(Message(role="user", content=prompt),),
        max_tokens=200,
        prompt_id="github_models_live",
        prompt_version="v1",
    )
    result = await client.complete_json(request, Judgment)
    assert 1 <= result.score <= 5
    assert recorder.rows[0]["cost_usd"] == 0.0
