"""Model clients of ``scripts/generate_qa.py``: the datagen client and the pass-2 judge (T4.2).

The datagen client is the VM CPU model (``PRUEFSTAND_DATAGEN_BACKEND=vm``, D1201; checked to
be the model served at ``PRUEFSTAND_DATAGEN_BASE_URL`` before any call) or GitHub Models
(``github``: retired on 2026-07-30, D1202; refused with that message unless a token is set).
"""

import os
from collections.abc import Callable

from generate_qa_args import REPO

from pruefstand.core.config import LLMPolicyConfig, ModelRef
from pruefstand.core.errors import ConfigError, StoreError
from pruefstand.core.models.attacks import CanaryRegistry
from pruefstand.core.settings import PruefstandSettings
from pruefstand.dataset.datagen_guard import build_datagen_client
from pruefstand.dataset.vm_datagen import check_vm_served
from pruefstand.llm.budget import Budget
from pruefstand.llm.client import LLMClient
from pruefstand.llm.factory import build_backend
from pruefstand.llm.policy import LLMPolicy, provider_of
from pruefstand.llm.recorder import CallRecorder
from pruefstand.store.canary_source import load_canary_registry
from pruefstand.store.kv import DiskKVCache

TOKEN_ENV = "PRUEFSTAND_GH_MODELS_TOKEN"  # noqa: S105  (a variable NAME, not a secret)

ClientFactory = Callable[[ModelRef, int | None, CallRecorder], LLMClient]
JudgeFactory = Callable[[ModelRef], LLMClient]


def _canaries() -> CanaryRegistry:
    try:
        return load_canary_registry(root=REPO)
    except StoreError as exc:  # fail closed: no registry means no canary scan (ADR-0009)
        msg = f"the canary registry is unreadable ({exc}); refusing to run without the data guard"
        raise ConfigError(msg) from exc


def default_client(ref: ModelRef, max_requests: int | None, recorder: CallRecorder) -> LLMClient:
    """The datagen client: VM model or GitHub Models, cached on disk, public-text datagen policy."""
    if provider_of(ref.id) == "github":
        if not os.environ.get(TOKEN_ENV):
            msg = (
                f"GitHub Models is retired (2026-07-30, D1202): use PRUEFSTAND_DATAGEN_BACKEND=vm; "
                f"{TOKEN_ENV} is not set (a GitHub token with Models: read, D333)"
            )
            raise ConfigError(msg)
    else:
        check_vm_served(ref.id, PruefstandSettings().datagen_base_url)
    cache = DiskKVCache(PruefstandSettings().cache_dir, "llm")
    return build_datagen_client(
        ref, cache=cache, max_requests=max_requests, recorder=recorder, canaries=_canaries()
    )


def default_judge(ref: ModelRef) -> LLMClient:
    """The pass-2 client: a local model only, no cache."""
    policy = LLMPolicyConfig(allowed_providers=("ollama", "openai_compatible_local"))
    return LLMClient(
        build_backend(ref, policy=policy),
        None,
        Budget(None, None),
        CallRecorder(),
        LLMPolicy(policy, _canaries()),
    )
