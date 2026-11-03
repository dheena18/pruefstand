"""Cost and quota tables (T5.1 S7): every provider is free; GitHub Models has request quotas."""

from dataclasses import dataclass
from functools import cache
from importlib.resources import files

import yaml

from pruefstand.core.errors import ConfigError
from pruefstand.core.models.target import Usage
from pruefstand.llm.providers import catalogue_entry, server_gpus


@dataclass(frozen=True)
class Quota:
    """Free-tier limits of one model (``quotas.yaml``)."""

    requests_per_minute: int
    requests_per_day: int
    tokens_per_request: int


def _read(name: str) -> dict[str, object]:
    text = files("pruefstand.llm").joinpath(name).read_text("utf-8")
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        msg = f"{name} must hold a mapping"
        raise ConfigError(msg)
    return data


@cache
def _prices() -> dict[str, float]:
    table = _read("costs.yaml").get("usd_per_1k_tokens")
    if not isinstance(table, dict):
        msg = "costs.yaml: missing 'usd_per_1k_tokens'"
        raise ConfigError(msg)
    return {str(k): float(v) for k, v in table.items()}


def configured_providers() -> frozenset[str]:
    """Return the providers that have a price entry (all 0.0 USD)."""
    return frozenset(_prices())


def cost_usd(provider: str, usage: Usage) -> float:
    """Return the USD cost of ``usage`` at ``provider`` (0.0 for every configured provider).

    Raises:
        ConfigError: ``provider`` has no price entry; a paid provider must be priced explicitly.

    Examples:
        >>> cost_usd("github", Usage(prompt_tokens=1000, completion_tokens=10))
        0.0
    """
    if provider not in _prices():
        msg = f"provider '{provider}' has no entry in costs.yaml; price it explicitly first"
        raise ConfigError(msg)
    return _prices()[provider] * (usage.prompt_tokens + usage.completion_tokens) / 1000


def gpu_seconds(model_id: str, latency_ms: float) -> float:
    """Return the GPU seconds of one call: latency times the GPUs of the model's server.

    An upper bound (``all`` counts both GPUs). Non-``ollama/`` models use no A40 time.

    Raises:
        ConfigError: ``model_id`` is an ``ollama/`` id missing from the catalogue.
    """
    if not model_id.startswith("ollama/"):
        return 0.0
    return latency_ms / 1000 * server_gpus(catalogue_entry(model_id).server)


@cache
def _quotas() -> dict[str, Quota]:
    table = _read("quotas.yaml").get("models")
    if not isinstance(table, dict):
        msg = "quotas.yaml: missing 'models'"
        raise ConfigError(msg)
    return {
        f"github/{name}": Quota(
            int(row["requests_per_minute"]),
            int(row["requests_per_day"]),
            int(row["tokens_per_request"]),
        )
        for name, row in table.items()
    }


def quota_for(model_id: str) -> Quota | None:
    """Return the free-tier quota of a ``github/`` model, or None when none is listed."""
    return _quotas().get(model_id)
