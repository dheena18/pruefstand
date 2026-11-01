import pytest
import structlog.testing
from testsupport.llm_scenarios import echo_request

from pruefstand.core.config import LLMPolicyConfig, ModelRef
from pruefstand.core.errors import ConfigError, PolicyViolation
from pruefstand.core.ids import DocId, TenantId
from pruefstand.core.models.attacks import Canary, CanaryRegistry
from pruefstand.core.models.llm import LLMRequest, LLMRole, Message
from pruefstand.llm.backends.litellm import LiteLLMBackend
from pruefstand.llm.factory import build_backend
from pruefstand.llm.policy import LLMPolicy, provider_of

LOCAL = ModelRef(id="openai_compatible_local/qwen2.5-0.5b-instruct", family="qwen")


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


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8080/v1",
        "http://127.0.0.1:1/v1",
        "http://[::1]:8080/v1",
        "http://10.0.0.5:8080/v1",
        "http://172.16.3.4/v1",
        "http://172.31.255.1/v1",
        "http://192.168.1.2/v1",
        "http://llm:8080/v1",
        "http://llm-proxy:11500/v1",
    ],
)
def test_local_endpoints_are_accepted(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    monkeypatch.setenv("PRUEFSTAND_JUDGE_BASE_URL", url)
    backend = build_backend(LOCAL, policy=LLMPolicyConfig())
    assert isinstance(backend, LiteLLMBackend)
    assert backend.api_base == url


@pytest.mark.parametrize(
    "url",
    [
        "https://api.openai.com/v1",
        "http://8.8.8.8/v1",
        "http://172.32.0.1/v1",
        "http://169.254.169.254/v1",
        "http://evil.example.com/v1",
        "http://localhost.evil.com/v1",
        "ftp://localhost/v1",
        "localhost:8080",
        "not a url",
    ],
)
def test_external_endpoints_for_the_local_provider_are_refused(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    monkeypatch.setenv("PRUEFSTAND_JUDGE_BASE_URL", url)
    with pytest.raises(ConfigError, match="PRUEFSTAND_JUDGE_BASE_URL"):
        build_backend(LOCAL, policy=LLMPolicyConfig())


@pytest.mark.parametrize("model_id", ["github", "github/", "/x", ""])
def test_provider_of_requires_provider_and_model(model_id: str) -> None:
    with pytest.raises(ConfigError, match="provider/model"):
        provider_of(model_id)


@pytest.mark.parametrize(
    "prompt_id", [" datagen.private_docs.x", "Datagen.Private_Docs.x", "DATAGEN.PRIVATE_DOCS.X\n"]
)
def test_private_prompt_ids_are_matched_after_normalisation(prompt_id: str) -> None:
    with pytest.raises(PolicyViolation, match="private documents"):
        LLMPolicy(LLMPolicyConfig()).check(_github("x", prompt_id), "github")


@pytest.mark.parametrize(
    "text",
    [
        "was ist canary-7f3a?",
        "was ist CANARY-7f3a",
        "CANARY\u200b-7f3a",
        "CANA\u00adRY-7f3a",
        "\uff23\uff21\uff2e\uff21\uff32\uff39\uff0d7f3a",
        "Der  Vorstand\nheißt  Müller-Lüdenscheidt.",
        "der vorstand hei\u00dft m\u00fcller-l\u00fcdenscheidt.",
        "Der Vorstand heißt Mu\u0308ller-Lu\u0308denscheidt.",
        "DER VORSTAND HEISST MÜLLER-LÜDENSCHEIDT.",
    ],
)
def test_canaries_are_found_through_normalisation(text: str) -> None:
    policy = LLMPolicy(LLMPolicyConfig(), canaries=_canary_registry())
    with pytest.raises(PolicyViolation, match="canary"):
        policy.check(_github(text), "github")


def test_datagen_is_denied_for_external_providers_unless_allowed() -> None:
    req = _github("Schreibe eine Frage.").model_copy(update={"role": LLMRole.DATAGEN})
    with pytest.raises(PolicyViolation, match="datagen"):
        LLMPolicy(LLMPolicyConfig()).check(req, "github")
    LLMPolicy(LLMPolicyConfig(), external_datagen=True).check(req, "github")
    local = req.model_copy(update={"model": "ollama/gemma3:12b"})
    LLMPolicy(LLMPolicyConfig()).check(local, "ollama")


def test_external_use_without_a_canary_registry_logs_a_warning() -> None:
    with structlog.testing.capture_logs() as logs:
        LLMPolicy(LLMPolicyConfig()).check(_github("harmlos"), "github")
    assert any(entry["log_level"] == "warning" for entry in logs)
    with structlog.testing.capture_logs() as logs:
        LLMPolicy(LLMPolicyConfig(), canaries=_canary_registry()).check(
            _github("harmlos"), "github"
        )
    assert not logs


@pytest.mark.parametrize(
    "dash", ["\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2015", "\u2212"]
)
def test_unicode_hyphens_do_not_hide_a_canary(dash: str) -> None:
    policy = LLMPolicy(LLMPolicyConfig(), canaries=_canary_registry())
    with pytest.raises(PolicyViolation, match="canary"):
        policy.check(_github(f"Was ist CANARY{dash}7f3a?"), "github")
