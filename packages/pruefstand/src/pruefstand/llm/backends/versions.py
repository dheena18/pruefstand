"""Provider-reported model version for the cache key (interfaces §8, D113).

Ollama: the served tag and its manifest digest from ``GET /api/tags`` (cross-checked with the
catalogue pin); llama.cpp: a hash of the model path from ``GET /props``. GitHub Models reports its
version in each response, so there is nothing to probe.
"""

import hashlib

import httpx

from pruefstand.core.hashing import stable_hash
from pruefstand.core.logging import get_logger
from pruefstand.llm.providers import catalogue_entry

_log = get_logger(__name__)
_PROBE_TIMEOUT_S = 10.0
_MAX_BYTES = 4_000_000
_DIGEST_CHARS = 12


def _get_json(url: str) -> object:
    with httpx.Client(timeout=_PROBE_TIMEOUT_S, follow_redirects=False) as client:
        response = client.get(url, headers={"Accept-Encoding": "identity"})
        response.raise_for_status()
        if len(response.content) > _MAX_BYTES:
            msg = "version probe answer too large"
            raise ValueError(msg)
        return response.json()


def ollama_version(base: str, model_id: str) -> str | None:
    """Return ``<tag>@<digest[:12]>`` of the served model, or None when it is not listed.

    A digest that differs from the catalogue pin is logged (the key still carries the served
    digest, so a different model never shares cache entries).
    """
    tag = model_id.removeprefix("ollama/")
    data = _get_json(f"{base.rstrip('/')}/api/tags")
    models = data.get("models") if isinstance(data, dict) else None
    for row in models if isinstance(models, list) else []:
        if isinstance(row, dict) and row.get("name") in {tag, f"{tag}:latest"}:
            digest = str(row.get("digest", "")).removeprefix("sha256:")
            if not digest:
                return None
            pin = catalogue_entry(model_id).digest
            if pin and pin != digest:
                _log.warning("ollama_digest_differs_from_catalogue", model=model_id)
            entry = catalogue_entry(model_id)
            effective = stable_hash(sorted(entry.options.items()), "think=false")
            return f"{tag}@{digest[:_DIGEST_CHARS]}|opts={effective[:_DIGEST_CHARS]}"
    return None


def llamacpp_version(api_base: str) -> str | None:
    """Return a short hash of the model path reported by ``GET /props``, or None."""
    origin = api_base.rstrip("/").removesuffix("/v1")
    data = _get_json(f"{origin}/props")
    if not isinstance(data, dict):
        return None
    path = data.get("model_path") or data.get("model_alias")
    if not path:
        return None
    return "props:" + hashlib.sha256(str(path).encode()).hexdigest()[:_DIGEST_CHARS]
