"""``build_backend``: model id -> backend, refusing providers the policy does not allow."""

import ipaddress
from urllib.parse import urlparse

from pruefstand.core.config import LLMPolicyConfig, ModelRef, PruefstandConfig
from pruefstand.core.errors import ConfigError
from pruefstand.core.models.attacks import CanaryRegistry
from pruefstand.core.protocols import KVCache, LLMBackend
from pruefstand.core.settings import PruefstandSettings
from pruefstand.llm.backends.litellm import GITHUB_MODELS_URL, LiteLLMBackend, litellm_model
from pruefstand.llm.budget import Budget
from pruefstand.llm.cache_epochs import current_epoch
from pruefstand.llm.client import LLMClient
from pruefstand.llm.policy import LLMPolicy, is_paid, provider_of, validate_policy_config
from pruefstand.llm.providers import ollama_base_url
from pruefstand.llm.recorder import CallRecorder

DEFAULT_LOCAL_URL = "http://localhost:8080/v1"
GH_MODELS_TOKEN_ENV = "PRUEFSTAND_GH_MODELS_TOKEN"  # noqa: S105  (a variable NAME, not a secret)
DEFAULT_TIMEOUT_S = 120.0
_UNCAPPED_FREE_TIERS = frozenset({"mistral", "gemini", "groq", "openrouter"})
_LITELLM_PREFIXES = ("ollama_chat/", "openai/")
_LOCAL_HOSTS = frozenset({"localhost", "llm", "llm-proxy", "embed", "rerank-cpu"})
_PRIVATE_NETS = tuple(
    ipaddress.ip_network(n)
    for n in ("127.0.0.0/8", "::1/128", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)


def _require_local_url(url: str, name: str = "PRUEFSTAND_JUDGE_BASE_URL") -> str:
    """Return ``url`` if it points at loopback, RFC1918 or a compose service; else ConfigError."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    ok = parsed.scheme in ("http", "https") and bool(host)
    if ok and host not in _LOCAL_HOSTS:
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            ok = False
        else:
            ok = any(ip in net for net in _PRIVATE_NETS)
    if not ok:
        msg = (
            f"{name} must be an http(s) URL on loopback, a private network "
            f"or a compose service for local providers (host '{host}')"
        )
        raise ConfigError(msg)
    return url


def _validate(ref: ModelRef, policy: LLMPolicyConfig) -> str:
    """Check ``ref`` against ``policy``; return its provider."""
    validate_policy_config(policy)
    provider = provider_of(ref.id)
    if provider in _UNCAPPED_FREE_TIERS:
        msg = (
            f"provider '{provider}' has no capped HTTP client yet; it is refused until T5.1 "
            "adds one (response size and decompression limits)"
        )
        raise ConfigError(msg)
    _refuse_litellm_prefix(ref, provider, policy)
    if provider not in policy.allowed_providers:
        msg = f"provider '{provider}' not in allowed_providers"
        raise ConfigError(msg)
    if is_paid(provider, ref.id) and not policy.allow_paid:
        msg = f"provider '{provider}' is paid and allow_paid is false"
        raise ConfigError(msg)
    return provider


def build_backend(ref: ModelRef, *, policy: LLMPolicyConfig) -> LLMBackend:
    """Build the backend for ``ref`` under ``policy``.

    ``api_base`` comes from ``PruefstandSettings`` by provider prefix:
    ``openai_compatible_local/`` uses ``PRUEFSTAND_JUDGE_BASE_URL`` (default
    ``http://localhost:8080/v1``); ``github/`` uses ``https://models.github.ai/inference`` with
    the key read from ``PRUEFSTAND_GH_MODELS_TOKEN`` at call time; ``ollama/`` reads the env var
    that ``infra/gpu/endpoints.yaml`` names for the model (never the catalogue: options are looked
    up when a request is made).

    Args:
        ref: Model id (``<provider>/<model>``) and family.
        policy: Allowed providers and ``allow_paid``.

    Returns:
        A ``LiteLLMBackend``.

    Raises:
        ConfigError: Policy invalid; provider not allowed or paid; a LiteLLM prefix in the id
            (D221); the endpoints file is unreadable or the env var it names is unset.
    """
    provider = _validate(ref, policy)
    litellm_model(ref)
    settings = PruefstandSettings()
    if provider == "openai_compatible_local":
        base = _require_local_url(settings.judge_base_url or DEFAULT_LOCAL_URL)
        return LiteLLMBackend(ref.id, api_base=base, api_key_env=None, timeout_s=DEFAULT_TIMEOUT_S)
    if provider == "ollama":
        base = _require_local_url(ollama_base_url(ref.id), "the Ollama base URL setting")
        return LiteLLMBackend(ref.id, api_base=base, api_key_env=None, timeout_s=DEFAULT_TIMEOUT_S)
    if provider == "github":
        return LiteLLMBackend(
            ref.id,
            api_base=GITHUB_MODELS_URL,
            api_key_env=GH_MODELS_TOKEN_ENV,
            timeout_s=DEFAULT_TIMEOUT_S,
        )
    return LiteLLMBackend(ref.id, api_base=None, api_key_env=None, timeout_s=DEFAULT_TIMEOUT_S)


def _refuse_litellm_prefix(ref: ModelRef, provider: str, policy: LLMPolicyConfig) -> None:
    for prefix in _LITELLM_PREFIXES:
        if ref.id.startswith(prefix):
            reasons = [
                f"model id '{ref.id}': the prefix '{prefix}' is a LiteLLM detail, "
                "not a config value (D221)"
            ]
            if provider not in policy.allowed_providers:
                reasons.append(f"provider '{provider}' not in allowed_providers")
            raise ConfigError("; ".join(reasons))


def build_client(
    cfg: PruefstandConfig,
    cache: KVCache | None,
    budget: Budget,
    recorder: CallRecorder,
    *,
    model: ModelRef | None = None,
    canaries: CanaryRegistry | None = None,
    external_datagen: bool = False,
) -> LLMClient:
    """Build the ``LLMClient`` for one model: policy, optional fallback judge, cache epochs.

    Args:
        cfg: The run configuration (``cfg.llm`` is the provider policy and the fallback judge).
        cache: The ``llm`` namespace cache of the run, or None.
        budget: The run budget.
        recorder: Receives the call rows.
        model: The model this client serves; default ``cfg.judge.pr``.
        canaries: Registry for the external-provider data guard.
        external_datagen: Allow public-text datagen to external providers (T4.2 only).

    Returns:
        The client; cache epochs are read from ``PRUEFSTAND_CACHE_DIR/cache_epochs.json``.

    Raises:
        ConfigError: A backend cannot be built (see ``build_backend``).
    """
    ref = model or cfg.judge.pr
    backend = build_backend(ref, policy=cfg.llm)
    fallback_ref = cfg.llm.fallback_judge
    fallback = build_backend(fallback_ref, policy=cfg.llm) if fallback_ref is not None else None
    cache_dir = PruefstandSettings().cache_dir
    return LLMClient(
        backend,
        cache,
        budget,
        recorder,
        LLMPolicy(cfg.llm, canaries, external_datagen=external_datagen),
        fallback=fallback,
        epochs=lambda name: current_epoch(cache_dir, name),
    )
