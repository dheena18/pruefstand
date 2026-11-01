"""Optional GitHub Models call: runs only with a token and a pinned model id (free quota)."""

import os

import pytest
from pydantic import BaseModel

from pruefstand.core.config import LLMPolicyConfig, ModelRef
from pruefstand.core.errors import LLMError
from pruefstand.core.models.llm import LLMRequest, LLMRole
from pruefstand.llm.budget import Budget
from pruefstand.llm.client import LLMClient
from pruefstand.llm.factory import build_backend
from pruefstand.llm.policy import LLMPolicy
from pruefstand.llm.prompts import PromptRegistry
from pruefstand.llm.recorder import CallRecorder

pytestmark = pytest.mark.live


class Probe(BaseModel):
    reason: str
    score: int


@pytest.mark.skipif(
    not (
        os.environ.get("PRUEFSTAND_GH_MODELS_TOKEN")
        and os.environ.get("PRUEFSTAND_GH_MODELS_MODEL")
    ),
    reason="PRUEFSTAND_GH_MODELS_TOKEN / PRUEFSTAND_GH_MODELS_MODEL not set",
)
async def test_github_models_json_probe() -> None:
    model = "github/" + os.environ["PRUEFSTAND_GH_MODELS_MODEL"].removeprefix("github/")
    policy = LLMPolicyConfig()
    backend = build_backend(ModelRef(id=model, family="unknown"), policy=policy)
    client = LLMClient(
        backend, None, Budget(max_usd=None, max_tokens=None), CallRecorder(), LLMPolicy(policy)
    )
    messages = (
        PromptRegistry()
        .get("json_probe", "v1")
        .render(sentence="Die Kündigung muss schriftlich erfolgen.")
    )
    req = LLMRequest(
        role=LLMRole.JUDGE,
        model=model,
        messages=messages,
        max_tokens=256,
        prompt_id="json_probe",
        prompt_version="v1",
    )
    try:
        parsed = await client.complete_json(req, Probe)
    except LLMError as err:
        if err.status == 429:
            pytest.xfail("free quota")
        raise
    assert parsed.reason
