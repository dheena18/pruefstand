"""Plumbing helpers for the LLM-perturbation tests: real ``LLMClient`` over a scripted loopback.

The loopback answers are fixed texts, so these tests prove the plumbing and the decision logic of
the perturbation code (parsing, checks, routing, resume), not model behaviour. Model behaviour is
covered by cassettes recorded from the real pinned models (``make cassettes``) and the ``live``
tests.
"""

import json

from testsupport.llm_scenarios import DictCache
from testsupport.loopback import completion_json
from testsupport.loopback_script import Step

from pruefstand.core.config import LLMPolicyConfig
from pruefstand.core.models.attacks import CanaryRegistry
from pruefstand.llm.backends.litellm import LiteLLMBackend
from pruefstand.llm.budget import Budget
from pruefstand.llm.client import LLMClient
from pruefstand.llm.policy import LLMPolicy
from pruefstand.llm.recorder import CallRecorder
from pruefstand.llm.retry import RetryPolicy

KEY_ENV = "PRUEFSTAND_TEST_KEY"
REWRITER = "github/test/gpt-rewrite"  # family gpt
SECOND = "github/test/mistral-second"  # family mistral
JUDGE = "openai_compatible_local/gemma3-test"  # family gemma
LOCAL_REWRITER = "openai_compatible_local/gemma3-local"  # family gemma


def answers(*texts: str) -> list[Step]:
    """Scripted HTTP answers, one per text, in call order."""
    return [Step(body=completion_json(t)) for t in texts]


def verdict(score: int, reason: str = "ok") -> str:
    """The JSON an equivalence check answers."""
    return json.dumps({"reason": reason, "score": score})


def client(
    base: str,
    model: str,
    *,
    canaries: CanaryRegistry | None = None,
    cache: DictCache | None = None,
    max_requests: int | None = None,
) -> LLMClient:
    """A real ``LLMClient`` for ``model`` against the loopback at ``base``."""
    backend = LiteLLMBackend(model, api_base=f"{base}/v1", api_key_env=KEY_ENV, timeout_s=30)
    return LLMClient(
        backend,
        cache,
        Budget(max_usd=None, max_tokens=None, max_requests=max_requests),
        CallRecorder(),
        LLMPolicy(LLMPolicyConfig(), canaries or CanaryRegistry(canaries=())),
        retry=RetryPolicy(max_retries=0),
    )
