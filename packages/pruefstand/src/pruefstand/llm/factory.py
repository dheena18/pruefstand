"""``build_backend``: model id -> backend, refusing providers the policy does not allow."""

import ipaddress
from urllib.parse import urlparse

from pruefstand.core.config import LLMPolicyConfig, ModelRef
from pruefstand.core.errors import ConfigError
from pruefstand.core.protocols import LLMBackend
from pruefstand.core.settings import PruefstandSettings
from pruefstand.llm.backends.litellm import LiteLLMBackend, litellm_model
from pruefstand.llm.policy import is_paid, provider_of, validate_policy_config

DEFAULT_LOCAL_URL = "http://localhost:8080/v1"
GITHUB_MODELS_URL = (
    "https://models.github.ai/inference"  # LiteLLM's own default host does not resolve (D347 g)
)
GH_MODELS_TOKEN_ENV = "PRUEFSTAND_GH_MODELS_TOKEN"  # noqa: S105  (a variable NAME, not a secret)
DEFAULT_TIMEOUT_S = 120.0
_LITELLM_PREFIXES = ("ollama_chat/", "openai/")
_LOCAL_HOSTS = frozenset({"localhost", "llm", "llm-proxy", "embed", "rerank-cpu"})
_PRIVATE_NETS = tuple(
    ipaddress.ip_network(n)
    for n in ("127.0.0.0/8", "::1/128", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)


def _require_local_url(url: str) -> str:
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
            "PRUEFSTAND_JUDGE_BASE_URL must be an http(s) URL on loopback, a private network "
            f"or a compose service for openai_compatible_local/ (host '{host}')"
        )
        raise ConfigError(msg)
    return url


def build_backend(ref: ModelRef, *, policy: LLMPolicyConfig) -> LLMBackend:
    """Build the backend for ``ref`` under ``policy``.

    ``api_base`` comes from ``PruefstandSettings`` by provider prefix:
    ``openai_compatible_local/`` uses ``PRUEFSTAND_JUDGE_BASE_URL`` (default
    ``http://localhost:8080/v1``); ``github/`` uses ``https://models.github.ai/inference`` with
    the key read from ``PRUEFSTAND_GH_MODELS_TOKEN`` at call time.

    Args:
        ref: Model id (``<provider>/<model>``) and family.
        policy: Allowed providers and ``allow_paid``.

    Returns:
        A ``LiteLLMBackend``.

    Raises:
        ConfigError: Policy invalid; provider not allowed or paid; a LiteLLM prefix in the id
            (D221); ``ollama/`` before the endpoint table of T5.1 exists.
    """
    validate_policy_config(policy)
    provider = provider_of(ref.id)
    _refuse_litellm_prefix(ref, provider, policy)
    if provider not in policy.allowed_providers:
        msg = f"provider '{provider}' not in allowed_providers"
        raise ConfigError(msg)
    if is_paid(provider, ref.id) and not policy.allow_paid:
        msg = f"provider '{provider}' is paid and allow_paid is false"
        raise ConfigError(msg)
    litellm_model(ref)
    settings = PruefstandSettings()
    if provider == "openai_compatible_local":
        base = _require_local_url(settings.judge_base_url or DEFAULT_LOCAL_URL)
        return LiteLLMBackend(ref.id, api_base=base, api_key_env=None, timeout_s=DEFAULT_TIMEOUT_S)
    if provider == "ollama":
        msg = "A40 endpoints are resolved from infra/gpu/endpoints.yaml (T5.1)"
        raise ConfigError(msg)
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
