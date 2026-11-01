"""Provider policy: free providers only, no paid provider without ``allow_paid``, data guard."""

import unicodedata

from pruefstand.core.config import LLMPolicyConfig
from pruefstand.core.errors import ConfigError, PolicyViolation
from pruefstand.core.logging import get_logger
from pruefstand.core.models.attacks import CanaryRegistry
from pruefstand.core.models.llm import LLMRequest, LLMRole

FREE_PROVIDERS = frozenset(
    {"openai_compatible_local", "ollama", "github", "mistral", "gemini", "groq", "openrouter"}
)
LOCAL_PROVIDERS = frozenset({"openai_compatible_local", "ollama"})
PRIVATE_PROMPT_PREFIX = "datagen.private_docs"
_log = get_logger(__name__)
# U+2010..U+2015 and U+2212 are not folded by NFKC (U+2011 included); an attacker may swap them in.
_HYPHENS = dict.fromkeys((*range(8208, 8214), 8722), "-")


def normalise(text: str) -> str:
    """Fold text for matching: NFKC, no format characters, one space, casefolded.

    Examples:
        >>> normalise("CAN\u00adARY\u200b  \uff11")
        'canary 1'
    """
    folded = unicodedata.normalize("NFKC", text).translate(_HYPHENS)
    kept = "".join(c for c in folded if unicodedata.category(c) != "Cf")
    return " ".join(kept.split()).casefold()


def provider_of(model_id: str) -> str:
    """Return the provider prefix of a model id.

    Raises:
        ConfigError: ``model_id`` is not ``provider/model`` with both parts non-empty.

    Examples:
        >>> provider_of("github/meta/llama-3.3-70b-instruct")
        'github'
    """
    provider, sep, model = model_id.partition("/")
    if not (sep and provider and model.strip()):
        msg = f"model id '{model_id}' must be of the form provider/model"
        raise ConfigError(msg)
    return provider


def is_paid(provider: str, model_id: str = "") -> bool:
    """Return True unless ``provider`` is on the free list of ADR-0009.

    OpenRouter counts as free only for ``:free`` model ids (when a model id is given).

    Examples:
        >>> is_paid("github"), is_paid("openai"), is_paid("openrouter", "openrouter/x:free")
        (False, True, False)
    """
    if provider == "openrouter" and model_id:
        return not model_id.endswith(":free")
    return provider not in FREE_PROVIDERS


def validate_policy_config(cfg: LLMPolicyConfig) -> None:
    """Check the policy shape at config load (T1.2 left this to T1.4).

    Args:
        cfg: The ``llm`` section of the run config.

    Raises:
        ConfigError: A listed provider is paid while ``allow_paid`` is false, or the fallback
            judge uses a provider that is not listed.
    """
    for name in cfg.allowed_providers:
        if is_paid(name) and not cfg.allow_paid:
            msg = (
                f"provider '{name}' is not a free provider; "
                "paid providers need allow_paid: true (ADR-0009)"
            )
            raise ConfigError(msg)
    fallback = cfg.fallback_judge
    if fallback is not None and provider_of(fallback.id) not in cfg.allowed_providers:
        msg = f"fallback judge provider '{provider_of(fallback.id)}' not in allowed_providers"
        raise ConfigError(msg)


class LLMPolicy:
    """Request-time provider policy.

    Args:
        cfg: Allowed providers and ``allow_paid``.
        canaries: Registry whose tokens and facts must never reach an external provider.
        external_datagen: Allow ``LLMRole.DATAGEN`` requests to external providers (public-text
            datagen on GitHub Models, T4.2); off by default.

    Raises:
        ConfigError: ``cfg`` fails ``validate_policy_config``.
    """

    def __init__(
        self,
        cfg: LLMPolicyConfig,
        canaries: CanaryRegistry | None = None,
        *,
        external_datagen: bool = False,
    ) -> None:
        validate_policy_config(cfg)
        self._cfg = cfg
        self._canaries = canaries
        self._external_datagen = external_datagen

    def check(self, req: LLMRequest, provider: str) -> None:
        """Refuse the request before any network call.

        Args:
            req: The request about to be sent.
            provider: The provider that would serve it.

        Raises:
            PolicyViolation: Provider not allowed, paid without ``allow_paid``, not the provider of
                ``req.model``, or private documents / canaries headed for an external provider.
        """
        if provider != provider_of(req.model):
            msg = f"provider '{provider}' does not match model '{req.model}'"
            raise PolicyViolation(msg)
        if provider not in self._cfg.allowed_providers:
            msg = f"provider '{provider}' not in allowed_providers"
            raise PolicyViolation(msg)
        if is_paid(provider, req.model) and not self._cfg.allow_paid:
            msg = f"provider '{provider}' is paid and allow_paid is false"
            raise PolicyViolation(msg)
        if provider not in LOCAL_PROVIDERS:
            self._check_data_guard(req, provider)

    def _check_data_guard(self, req: LLMRequest, provider: str) -> None:
        """Private documents and canary data never leave for an external provider (ADR-0009)."""
        if normalise(req.prompt_id).startswith(PRIVATE_PROMPT_PREFIX):
            msg = (
                f"prompt '{req.prompt_id}' holds private documents; "
                f"external provider '{provider}' refused"
            )
            raise PolicyViolation(msg)
        if req.role is LLMRole.DATAGEN and not self._external_datagen:
            msg = f"datagen requests may not use external provider '{provider}' (default deny)"
            raise PolicyViolation(msg)
        if self._canaries is None:
            _log.warning("external_provider_without_canary_registry", provider=provider)
            return
        text = normalise("\n".join(m.content for m in req.messages))
        for canary in self._canaries.canaries:
            fact = normalise(canary.fact) if canary.fact else None
            if normalise(canary.token) in text or (fact and fact in text):
                msg = f"canary data in the request; external provider '{provider}' refused"
                raise PolicyViolation(msg)
