import pytest
from testsupport.llm_scenarios import echo_request

from pruefstand.core.config import LLMPolicyConfig, ModelRef
from pruefstand.core.errors import ConfigError, LLMError, PolicyViolation
from pruefstand.core.ids import DocId, TenantId
from pruefstand.core.models.attacks import Canary, CanaryRegistry
from pruefstand.core.models.llm import LLMRequest, Message
from pruefstand.core.protocols import LLMBackend, LLMClientLike
from pruefstand.llm.backends.litellm import LiteLLMBackend, litellm_model
from pruefstand.llm.budget import Budget
from pruefstand.llm.client import LLMClient
from pruefstand.llm.factory import build_backend
from pruefstand.llm.policy import LLMPolicy, provider_of
from pruefstand.llm.recorder import CallRecorder

LOCAL = ModelRef(id="openai_compatible_local/qwen2.5-0.5b-instruct", family="qwen")


def test_local_backend_uses_the_judge_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRUEFSTAND_JUDGE_BASE_URL", "http://judge.test:9999/v1")
    backend = build_backend(LOCAL, policy=LLMPolicyConfig())
    assert isinstance(backend, LiteLLMBackend)
    assert backend.api_base == "http://judge.test:9999/v1"


def test_local_backend_default_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PRUEFSTAND_JUDGE_BASE_URL", raising=False)
    backend = build_backend(LOCAL, policy=LLMPolicyConfig())
    assert isinstance(backend, LiteLLMBackend)
    assert backend.api_base == "http://localhost:8080/v1"


def test_github_models_are_allowed_and_use_the_token_variable() -> None:
    ref = ModelRef(id="github/meta/llama-3.3-70b-instruct", family="llama")
    backend = build_backend(ref, policy=LLMPolicyConfig())
    assert isinstance(backend, LiteLLMBackend)
    assert backend.api_base is None
    assert backend.api_key_env == "PRUEFSTAND_GH_MODELS_TOKEN"


def test_ollama_waits_for_the_endpoint_table() -> None:
    ref = ModelRef(id="ollama/qwen3.8:27b-q8_0", family="qwen")
    with pytest.raises(ConfigError, match=r"infra/gpu/endpoints\.yaml"):
        build_backend(ref, policy=LLMPolicyConfig())


def test_paid_provider_is_refused() -> None:
    ref = ModelRef(id="openai/gpt-x", family="gpt")
    with pytest.raises(ConfigError, match="not in allowed_providers"):
        build_backend(ref, policy=LLMPolicyConfig())


def test_allow_paid_alone_does_not_allow_a_provider() -> None:
    ref = ModelRef(id="anthropic/claude-x", family="claude")
    with pytest.raises(ConfigError, match="not in allowed_providers"):
        build_backend(ref, policy=LLMPolicyConfig(allow_paid=True))


def test_paid_provider_listed_without_allow_paid_fails_at_load() -> None:
    cfg = LLMPolicyConfig(allowed_providers=("github", "anthropic"))
    with pytest.raises(ConfigError, match="anthropic"):
        LLMPolicy(cfg)
    with pytest.raises(ConfigError, match="anthropic"):
        build_backend(LOCAL, policy=cfg)


def test_opt_in_free_tier_may_be_listed() -> None:
    policy = LLMPolicy(LLMPolicyConfig(allowed_providers=("github", "mistral", "groq")))
    assert policy is not None


def test_policy_check_rejects_unlisted_provider_without_network() -> None:
    policy = LLMPolicy(LLMPolicyConfig())
    req = echo_request().model_copy(update={"model": "groq/llama-3.1-8b-instant"})
    with pytest.raises(PolicyViolation, match="not in allowed_providers") as info:
        policy.check(req, provider_of(req.model))
    assert isinstance(info.value, LLMError)
    assert info.value.transient is False


def test_policy_check_blocks_paid_provider_even_when_listed_if_not_allowed() -> None:
    cfg = LLMPolicyConfig(allowed_providers=("openai",), allow_paid=True)
    policy = LLMPolicy(cfg)
    req = echo_request().model_copy(update={"model": "openai/gpt-x"})
    policy.check(req, "openai")  # allowed: listed and allow_paid
    with pytest.raises(PolicyViolation):
        LLMPolicy(LLMPolicyConfig()).check(req, "openai")


def test_policy_check_accepts_the_default_providers() -> None:
    policy = LLMPolicy(LLMPolicyConfig())
    for model in ("openai_compatible_local/m", "ollama/qwen3:14b", "github/x/y"):
        req = echo_request().model_copy(update={"model": model})
        policy.check(req, provider_of(model))


@pytest.mark.parametrize(
    ("model_id", "expected"),
    [
        ("ollama/qwen3.8:27b-q8_0", "ollama_chat/qwen3.8:27b-q8_0"),
        ("openai_compatible_local/qwen2.5-0.5b-instruct", "openai/qwen2.5-0.5b-instruct"),
        ("github/meta/llama-3.3-70b-instruct", "github/meta/llama-3.3-70b-instruct"),
    ],
)
def test_litellm_model_translation(model_id: str, expected: str) -> None:
    assert litellm_model(ModelRef(id=model_id, family="qwen")) == expected


@pytest.mark.parametrize("model_id", ["ollama_chat/qwen3:14b", "openai/qwen3:14b"])
def test_litellm_prefixes_in_config_ids_are_refused(model_id: str) -> None:
    ref = ModelRef(id=model_id, family="qwen")
    with pytest.raises(ConfigError, match="D221"):
        litellm_model(ref)
    with pytest.raises(ConfigError, match="D221"):
        build_backend(ref, policy=LLMPolicyConfig())


def test_client_satisfies_the_structural_protocols() -> None:
    backend = LiteLLMBackend(
        LOCAL.id, api_base="http://localhost:8080/v1", api_key_env=None, timeout_s=5
    )
    client = LLMClient(
        backend,
        None,
        Budget(max_usd=None, max_tokens=None),
        CallRecorder(),
        LLMPolicy(LLMPolicyConfig()),
    )
    assert isinstance(client, LLMClientLike)
    assert isinstance(backend, LLMBackend)


def _canary_registry() -> CanaryRegistry:
    canary = Canary(
        token="CANARY-7f3a",  # noqa: S106  (test canary, not a credential)
        tenant=TenantId("t-a"),
        doc_id=DocId("d1"),
        kind="token",
        fact="Der Vorstand heißt Müller-Lüdenscheidt.",
        probe_question=None,
        forbidden_answer=None,
    )
    return CanaryRegistry(canaries=(canary,))


def _github(text: str, prompt_id: str = "echo") -> LLMRequest:
    return echo_request().model_copy(
        update={
            "model": "github/openai/gpt-4o-mini",
            "messages": (Message(role="user", content=text),),
            "prompt_id": prompt_id,
        }
    )


def test_private_document_prompts_never_go_to_an_external_provider() -> None:
    policy = LLMPolicy(LLMPolicyConfig())
    req = _github("Schreibe ein Dokument.", "datagen.private_docs.private_doc_de")
    with pytest.raises(PolicyViolation, match="private documents"):
        policy.check(req, "github")
    local = req.model_copy(update={"model": "openai_compatible_local/m"})
    policy.check(local, "openai_compatible_local")


def test_canary_token_and_fact_never_go_to_an_external_provider() -> None:
    policy = LLMPolicy(LLMPolicyConfig(), canaries=_canary_registry())
    with pytest.raises(PolicyViolation, match="canary"):
        policy.check(_github("Was ist CANARY-7f3a?"), "github")
    with pytest.raises(PolicyViolation, match="canary"):
        policy.check(_github("Wer? Der Vorstand heißt Müller-Lüdenscheidt."), "github")
    policy.check(_github("Eine harmlose Frage zur Kündigung."), "github")
    local = _github("Was ist CANARY-7f3a?").model_copy(update={"model": "ollama/gemma3:12b"})
    policy.check(local, "ollama")


def test_provider_must_match_the_model_prefix() -> None:
    with pytest.raises(PolicyViolation, match="does not match"):
        LLMPolicy(LLMPolicyConfig()).check(_github("x"), "ollama")


def test_fallback_judge_provider_must_be_listed() -> None:
    cfg = LLMPolicyConfig(
        allowed_providers=("github",),
        fallback_judge=ModelRef(id="ollama/gemma3:12b", family="gemma"),
    )
    with pytest.raises(ConfigError, match="fallback"):
        LLMPolicy(cfg)


def test_openrouter_is_free_only_for_free_models() -> None:
    cfg = LLMPolicyConfig(allowed_providers=("openrouter",))
    policy = LLMPolicy(cfg)
    ok = _github("x").model_copy(update={"model": "openrouter/meta/llama:free"})
    policy.check(ok, "openrouter")
    paid = ok.model_copy(update={"model": "openrouter/meta/llama"})
    with pytest.raises(PolicyViolation, match="paid"):
        policy.check(paid, "openrouter")
