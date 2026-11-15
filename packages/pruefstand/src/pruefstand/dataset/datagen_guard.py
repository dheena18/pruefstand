"""Datagen model rules and data guard (ADR-0019, D330, D1201): pinned models, public text only.

The datagen model is either one of the pinned VM CPU models (``openai_compatible_local/``, the
default backend since D1201, ``datagen_pins.VM_DATAGEN_MODELS``) or a GitHub Models id
(``github/``, retired 2026-07-30), of a family that is neither the generator's (``qwen``) nor the
judge's (``gemma``); any other local model (``ollama/``, another ``openai_compatible_local/`` id)
is refused. Private documents, canaries and held-out data are never routed here: ``generate_qa``
skips private and attack chunks itself, and the client guard of ``LLMPolicy`` blocks them for
every external provider.
"""

from pruefstand.core.config import LLMPolicyConfig, ModelRef
from pruefstand.core.errors import ConfigError
from pruefstand.core.models.attacks import CanaryRegistry
from pruefstand.core.protocols import KVCache
from pruefstand.core.settings import PruefstandSettings
from pruefstand.dataset.datagen_pins import VM_DATAGEN_MODELS
from pruefstand.dataset.vm_datagen import VM_PROVIDER, build_vm_backend
from pruefstand.llm.budget import Budget
from pruefstand.llm.client import LLMClient
from pruefstand.llm.factory import build_backend
from pruefstand.llm.families import family_of
from pruefstand.llm.policy import LLMPolicy, provider_of
from pruefstand.llm.recorder import CallRecorder
from pruefstand.llm.retry import RetryPolicy

DATAGEN_PROVIDER = "github"
FORBIDDEN_FAMILIES = frozenset({"qwen", "gemma"})


def datagen_policy(canaries: CanaryRegistry | None, provider: str = DATAGEN_PROVIDER) -> LLMPolicy:
    """Return the policy of the datagen client: one provider, public-text datagen allowed.

    Args:
        canaries: Registry whose tokens and facts must never reach an external provider; None
            logs a warning in ``LLMPolicy`` and skips the canary match (callers pass a registry).
        provider: ``github`` (external datagen allowed) or ``openai_compatible_local`` (the VM
            model; local, so ``LLMPolicy`` applies no external-provider guard to it).

    Raises:
        ConfigError: ``provider`` is neither of the two.
    """
    if provider not in {DATAGEN_PROVIDER, VM_PROVIDER}:
        msg = f"datagen provider '{provider}' is neither '{DATAGEN_PROVIDER}' nor '{VM_PROVIDER}'"
        raise ConfigError(msg)
    config = LLMPolicyConfig(allowed_providers=(provider,))
    return LLMPolicy(config, canaries, external_datagen=provider == DATAGEN_PROVIDER)


def check_datagen_model(model: str | ModelRef) -> str:
    """Check a datagen model id and return its family.

    Args:
        model: A pinned VM model id, ``github/<model>``, or a ``ModelRef`` whose declared
            family must agree.

    Returns:
        The family of the model.

    Raises:
        ConfigError: A local model that is not a VM pin, another provider, an id that
            matches no family, a declared family that contradicts the id, or the family
            ``qwen`` or ``gemma``.

    Examples:
        >>> check_datagen_model("github/openai/gpt-4.1-mini")
        'gpt'
        >>> check_datagen_model("openai_compatible_local/ministral-3-8b-instruct-2512")
        'mistral'
    """
    ref = model if isinstance(model, ModelRef) else None
    model_id = ref.id if ref else str(model)
    provider = provider_of(model_id)
    if provider in {"ollama", VM_PROVIDER} and model_id not in VM_DATAGEN_MODELS:
        pins = ", ".join(sorted(VM_DATAGEN_MODELS))
        msg = f"{model_id}: not a pinned local datagen model (D1201); use one of {pins}"
        raise ConfigError(msg)
    if provider not in {DATAGEN_PROVIDER, VM_PROVIDER}:
        msg = f"{model_id}: the datagen model must be a VM pin or a GitHub Models id (D1201)"
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
    """Build the client for one datagen model (VM or GitHub Models): policy, request cap, USD 0.

    The VM model is reached at ``PRUEFSTAND_DATAGEN_BASE_URL`` after ``check_vm_served``, with
    a 900 s timeout and NO transport retries: the one-slot CPU server would otherwise get
    resends that the request budget never sees (D1201).

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
    provider = provider_of(ref.id)
    config = LLMPolicyConfig(allowed_providers=(provider,))
    budget = Budget(max_usd=0.0, max_tokens=None, max_requests=max_requests)
    policy = datagen_policy(canaries, provider)
    if provider == VM_PROVIDER:
        backend = build_vm_backend(ref, PruefstandSettings().datagen_base_url)
        retry = RetryPolicy(max_retries=0)
        return LLMClient(backend, cache, budget, recorder, policy, retry=retry)
    return LLMClient(build_backend(ref, policy=config), cache, budget, recorder, policy)
