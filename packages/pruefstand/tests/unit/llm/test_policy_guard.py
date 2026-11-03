"""The data guard and the provider policy through ``LLMClient``: no network call on refusal."""

import pytest
from testsupport.llm_scenarios import echo_request
from testsupport.loopback_script import ScriptState, serve_script

from pruefstand.core.config import LLMPolicyConfig
from pruefstand.core.errors import ConfigError, PolicyViolation
from pruefstand.core.ids import DocId, TenantId
from pruefstand.core.models.attacks import Canary, CanaryRegistry
from pruefstand.core.models.llm import LLMRequest, Message
from pruefstand.llm.backends.litellm import LiteLLMBackend
from pruefstand.llm.budget import Budget
from pruefstand.llm.client import LLMClient
from pruefstand.llm.policy import LLMPolicy
from pruefstand.llm.recorder import CallRecorder

TOKEN = "CANARY-VN-" + "7f3a9c"
KEY_ENV = "PRUEFSTAND_TEST_KEY"


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(KEY_ENV, "synthetic-test-value")


def _registry() -> CanaryRegistry:
    canary = Canary(
        token=TOKEN,
        tenant=TenantId("t1"),
        doc_id=DocId("d1"),
        kind="token",
        fact="Der Vorstand heißt Meier.",
        probe_question=None,
        forbidden_answer=None,
    )
    return CanaryRegistry(canaries=(canary,))


def _client(base: str, model: str, policy: LLMPolicy) -> tuple[LLMClient, CallRecorder]:
    backend = LiteLLMBackend(model, api_base=f"{base}/v1", api_key_env=KEY_ENV, timeout_s=30)
    recorder = CallRecorder()
    return LLMClient(backend, None, Budget(None, None), recorder, policy), recorder


def _req(model: str, text: str = "Hallo", prompt_id: str = "echo") -> LLMRequest:
    return echo_request().model_copy(
        update={
            "model": model,
            "messages": (Message(role="user", content=text),),
            "prompt_id": prompt_id,
        }
    )


def _posts(state: ScriptState) -> int:
    return state.posts()


async def test_a_canary_to_github_is_refused_without_a_network_call() -> None:
    policy = LLMPolicy(LLMPolicyConfig(), canaries=_registry())
    with serve_script() as (base, state):
        client, recorder = _client(base, "github/t/m", policy)
        with pytest.raises(PolicyViolation):
            await client.complete(_req("github/t/m", f"Was ist {TOKEN}?"))
    assert _posts(state) == 0
    assert recorder.rows[0]["error"]


async def test_private_document_prompts_to_github_are_refused() -> None:
    policy = LLMPolicy(LLMPolicyConfig(), canaries=_registry())
    with serve_script() as (base, state):
        client, _ = _client(base, "github/t/m", policy)
        with pytest.raises(PolicyViolation):
            await client.complete(
                _req("github/t/m", prompt_id="datagen.private_docs.private_doc_de")
            )
    assert _posts(state) == 0


async def test_the_same_requests_to_a_local_provider_are_allowed() -> None:
    policy = LLMPolicy(LLMPolicyConfig(), canaries=_registry())
    model = "openai_compatible_local/m"
    with serve_script() as (base, state):
        client, _ = _client(base, model, policy)
        await client.complete(_req(model, f"Was ist {TOKEN}?"))
        await client.complete(_req(model, prompt_id="datagen.private_docs.private_doc_de"))
    assert _posts(state) == 2


async def test_a_provider_outside_allowed_providers_is_refused_at_request_time() -> None:
    policy = LLMPolicy(LLMPolicyConfig())
    with serve_script() as (base, state):
        client, _ = _client(base, "github/t/m", policy)
        with pytest.raises(PolicyViolation):
            await client.complete(_req("anthropic/claude-x"))
    assert _posts(state) == 0


def test_a_paid_provider_listed_without_allow_paid_fails_at_config_load() -> None:
    with pytest.raises(ConfigError):
        LLMPolicy(LLMPolicyConfig(allowed_providers=("github", "anthropic")))
