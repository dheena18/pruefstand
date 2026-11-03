"""Datagen model rules and data guard (ADR-0019, D330): GitHub Models only, public text only.

The datagen model is a pinned GitHub Models free-tier model of a family that is neither the
generator's (``qwen``) nor the judge's (``gemma``); there is no local datagen model for public
text. Private documents, canaries and held-out data are never routed here (the client guard of
``LLMPolicy`` blocks them for every external provider).
"""

from pruefstand.core.config import LLMPolicyConfig, ModelRef
from pruefstand.core.errors import ConfigError
from pruefstand.core.models.attacks import CanaryRegistry
from pruefstand.core.protocols import KVCache
from pruefstand.llm.budget import Budget
from pruefstand.llm.client import LLMClient
from pruefstand.llm.factory import build_backend
from pruefstand.llm.families import family_of
from pruefstand.llm.policy import LLMPolicy, provider_of
from pruefstand.llm.recorder import CallRecorder

DATAGEN_PROVIDER = "github"
FORBIDDEN_FAMILIES = frozenset({"qwen", "gemma"})


def datagen_policy(canaries: CanaryRegistry | None) -> LLMPolicy:
    """Return the policy of the datagen client: GitHub Models, public-text datagen allowed.

    Args:
        canaries: Registry whose tokens and facts must never reach GitHub Models; None logs a
            warning in ``LLMPolicy`` and skips the canary match (callers pass a registry).
    """
    config = LLMPolicyConfig(allowed_providers=(DATAGEN_PROVIDER,))
    return LLMPolicy(config, canaries, external_datagen=True)


def check_datagen_model(model: str | ModelRef) -> str:
    """Check a datagen model id and return its family.

    Args:
        model: ``github/<model>``, or a ``ModelRef`` whose declared family must agree.

    Returns:
        The family of the model.

    Raises:
        ConfigError: A local model (``ollama/``), another provider, an id that matches no family,
            a declared family that contradicts the id, or the family ``qwen`` or ``gemma``.

    Examples:
        >>> check_datagen_model("github/openai/gpt-4.1-mini")
        'gpt'
    """
    ref = model if isinstance(model, ModelRef) else None
    model_id = ref.id if ref else str(model)
    provider = provider_of(model_id)
    if provider in {"ollama", "openai_compatible_local"}:
        msg = (
            f"{model_id}: no local datagen model (ADR-0019); use a GitHub Models id github/<model>"
        )
        raise ConfigError(msg)
    if provider != DATAGEN_PROVIDER:
        msg = f"{model_id}: the datagen model must be a GitHub Models id github/<model> (ADR-0019)"
        raise ConfigError(msg)
    if ref is not None and ref.family in FORBIDDEN_FAMILIES:
        msg = (
            f"{model_id}: family '{ref.family}' is the generator's or the judge's family (ADR-0019)"
        )
        raise ConfigError(msg)
    family = family_of(model_id)
    if ref is not None and ref.family != family:
        msg = (
            f"{model_id}: declared family '{ref.family}' differs from the family table ('{family}')"
        )
        raise ConfigError(msg)
    if family in FORBIDDEN_FAMILIES:
        msg = f"{model_id}: family '{family}' is the generator's or the judge's family (ADR-0019)"
        raise ConfigError(msg)
    return family


def build_datagen_client(
    ref: ModelRef,
    *,
    cache: KVCache | None,
    max_requests: int | None,
    recorder: CallRecorder,
    canaries: CanaryRegistry,
) -> LLMClient:
    """Build the client for one GitHub Models datagen model: policy, request cap, USD cap 0.

    Args:
        ref: The model (checked with ``check_datagen_model``).
        cache: The ``llm`` cache of the run (answers are cached by the client), or None.
        max_requests: Cap on charged requests (``--max-requests``); None = no cap.
        recorder: Receives one row per call.
        canaries: Registry for the external-provider data guard (fails closed in the policy).

    Raises:
        ConfigError: The model is not an allowed datagen model, or the backend cannot be built.
    """
    check_datagen_model(ref)
    config = LLMPolicyConfig(allowed_providers=(DATAGEN_PROVIDER,))
    budget = Budget(max_usd=0.0, max_tokens=None, max_requests=max_requests)
    return LLMClient(
        build_backend(ref, policy=config), cache, budget, recorder, datagen_policy(canaries)
    )
