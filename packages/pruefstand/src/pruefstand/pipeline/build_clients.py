"""Model clients of ``build_dataset`` (T4.7a); tests pass their own ``BuildClients``.

* ``datagen``: GitHub Models, public text only, cached on disk (``dataset.datagen_guard``);
* ``local``: a local model (Ollama on the A40 cluster or a llama.cpp container), no cache; used for
  the support check, the rewrite validity check and the review;
* ``embed``: question vectors from the embedding server (TEI or Ollama, no credential).
"""

import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import httpx
import numpy as np
from numpy.typing import NDArray

from pruefstand.core.config import EmbedConfig, LLMPolicyConfig, ModelRef
from pruefstand.core.errors import ConfigError, DatasetError, StoreError
from pruefstand.core.models.attacks import CanaryRegistry
from pruefstand.core.settings import PruefstandSettings
from pruefstand.dataset.datagen_guard import build_datagen_client
from pruefstand.llm.budget import Budget
from pruefstand.llm.client import LLMClient
from pruefstand.llm.factory import build_backend
from pruefstand.llm.policy import LLMPolicy
from pruefstand.llm.recorder import CallRecorder
from pruefstand.store.canary_source import load_canary_registry
from pruefstand.store.kv import DiskKVCache

TOKEN_ENV = "PRUEFSTAND_GH_MODELS_TOKEN"  # noqa: S105  (a variable NAME, not a secret)
BATCH = 32
TIMEOUT_S = 60.0
Embedder = Callable[[Sequence[str]], NDArray[np.float32]]


@dataclass(frozen=True)
class BuildClients:
    """Factories of the three kinds of client; the default ones talk to the real services."""

    datagen: Callable[[ModelRef, int | None, CallRecorder], LLMClient]
    local: Callable[[ModelRef], LLMClient]
    embed: Callable[[EmbedConfig], Embedder]


def _canaries(root: Path) -> CanaryRegistry:
    try:
        return load_canary_registry(root=root)
    except StoreError as exc:  # fail closed: no registry means no canary scan (ADR-0009)
        msg = f"the canary registry is unreadable ({exc}); refusing to run without the data guard"
        raise ConfigError(msg) from exc


def default_datagen(root: Path) -> Callable[[ModelRef, int | None, CallRecorder], LLMClient]:
    """Return the datagen factory: GitHub Models with the token ``PRUEFSTAND_GH_MODELS_TOKEN``."""

    def make(ref: ModelRef, max_requests: int | None, recorder: CallRecorder) -> LLMClient:
        if not os.environ.get(TOKEN_ENV):
            msg = f"{TOKEN_ENV} is not set (a GitHub token with Models: read, D333)"
            raise ConfigError(msg)
        cache = DiskKVCache(PruefstandSettings().cache_dir, "llm")
        return build_datagen_client(
            ref,
            cache=cache,
            max_requests=max_requests,
            recorder=recorder,
            canaries=_canaries(root),
        )

    return make


def default_local(root: Path) -> Callable[[ModelRef], LLMClient]:
    """Return the local-model factory (``ollama`` and local OpenAI-compatible servers only)."""

    def make(ref: ModelRef) -> LLMClient:
        policy = LLMPolicyConfig(allowed_providers=("ollama", "openai_compatible_local"))
        return LLMClient(
            build_backend(ref, policy=policy),
            None,
            Budget(None, None),
            CallRecorder(),
            LLMPolicy(policy, _canaries(root)),
        )

    return make


def _post(client: httpx.Client, url: str, body: dict[str, object]) -> object:
    try:
        response = client.post(url, json=body)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        msg = f"embedding request failed ({type(exc).__name__})"
        raise DatasetError(msg) from exc


def make_embedder(
    url: str, api: Literal["tei", "ollama"], model: str, *, client: httpx.Client | None = None
) -> Embedder:
    """Return a function that embeds texts in batches of 32 (``tei`` or ``ollama`` API)."""
    http = client or httpx.Client(timeout=TIMEOUT_S)
    base = url.rstrip("/")

    def embed(texts: Sequence[str]) -> NDArray[np.float32]:
        rows: list[object] = []
        for start in range(0, len(texts), BATCH):
            batch = list(texts[start : start + BATCH])
            if api == "tei":
                data = _post(http, f"{base}/embed", {"inputs": batch, "truncate": True})
            else:
                body = _post(http, f"{base}/api/embed", {"model": model, "input": batch})
                data = body.get("embeddings") if isinstance(body, dict) else None
            if not isinstance(data, list) or len(data) != len(batch):
                msg = "embedding server answered with an unexpected shape"
                raise DatasetError(msg)
            rows.extend(data)
        return np.asarray(rows, dtype=np.float32).reshape(len(texts), -1)

    return embed


def default_clients(root: Path) -> BuildClients:
    """The real clients; ``root`` is the repository root (canary registry, cache)."""
    return BuildClients(
        datagen=default_datagen(root),
        local=default_local(root),
        embed=lambda cfg: make_embedder(cfg.url, cfg.api, cfg.model),
    )
