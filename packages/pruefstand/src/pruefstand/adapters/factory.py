"""Adapter factory: ``build_adapter`` maps ``TargetConfig.type`` to an adapter (interfaces §4)."""

from pruefstand.adapters.http import HttpTargetAdapter
from pruefstand.core.config import HttpTargetConfig, TargetConfig
from pruefstand.core.errors import ConfigError
from pruefstand.core.protocols import TargetAdapter


def build_adapter(cfg: TargetConfig) -> TargetAdapter:
    """Build the adapter for ``cfg.type``.

    Only ``http`` exists (there is no simulated target, ADR-0008; T10.3 adds framework
    adapters).

    Args:
        cfg: Target configuration.

    Returns:
        An adapter that is not yet connected; the caller closes it with ``aclose``.

    Raises:
        ConfigError: ``cfg.type`` is unknown, or the URL is not a plain http(s) URL.
    """
    kind: str = cfg.type  # widened: models built with model_construct may carry other values
    if kind == "http":
        return HttpTargetAdapter(HttpTargetConfig.model_validate(cfg.model_dump()))
    msg = f"unknown target type {kind!r}; supported: http"
    raise ConfigError(msg)
