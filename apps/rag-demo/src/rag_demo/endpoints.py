"""Endpoint rules of rag-demo: no hosted provider, native Ollama API only (W3.15, D219, D221)."""

import os
from collections.abc import Mapping
from urllib.parse import urlsplit

from rag_demo.errors import ConfigError

# localhost, the gate route (D242) and the compose service names on the internal network.
INTERNAL_HOSTS = frozenset(
    {"localhost", "127.0.0.1", "llm-proxy", "rerank-cpu", "qdrant", "llm", "embed"}
)
OLLAMA_PREFIX = "ollama/"


def check_endpoint(url: str, *, engine: str) -> None:
    """Reject an endpoint that is not internal, or an Ollama endpoint on the ``/v1`` API.

    Args:
        url: The base URL of a generator, embedding or rerank service.
        engine: The engine behind it (``"ollama"`` forbids a ``/v1`` path).

    Raises:
        ConfigError: The host is not ``localhost``/``127.0.0.1``/``llm-proxy`` or an internal
            service name (W3.15), or an Ollama endpoint path contains ``/v1`` (D219).

    Examples:
        >>> check_endpoint("http://llm-proxy:11500", engine="ollama")
    """
    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.scheme not in {"http", "https"} or host not in INTERNAL_HOSTS:
        msg = (
            f"endpoint host {host!r} is not internal (W3.15: rag-demo never calls an external "
            "provider; allowed: localhost, 127.0.0.1, llm-proxy and the internal service names)"
        )
        raise ConfigError(msg)
    if engine == "ollama" and "v1" in parts.path.split("/"):
        msg = f"Ollama endpoint {url!r} uses /v1; only the native /api/* API is allowed (D219)"
        raise ConfigError(msg)


def check_served(
    *,
    engine: str,
    catalogue_id: str | None,
    endpoint_env: str | None,
    base_url: str | None,
    options: Mapping[str, float],
) -> None:
    """Validate the fields every served model section (generator, embed) shares.

    Raises:
        ConfigError: Bare tag or missing catalogue id for Ollama (D221), both ``base_url`` and
            ``endpoint_env``, a missing ``options.num_ctx`` (Ollama), an unknown option, or a
            bad ``base_url`` (see ``check_endpoint``).
    """
    if engine == "ollama":
        if catalogue_id is None or not catalogue_id.startswith(OLLAMA_PREFIX):
            msg = f"catalogue_id {catalogue_id!r} must have the form ollama/<tag> (D221)"
            raise ConfigError(msg)
        if "num_ctx" not in options:
            msg = "options.num_ctx is required for engine ollama (it must equal the catalogue)"
            raise ConfigError(msg)
    if set(options) - {"num_ctx", "top_p"}:
        msg = "options may only hold num_ctx and top_p (sampling comes from generation, N2)"
        raise ConfigError(msg)
    if base_url is not None and endpoint_env is not None:
        msg = "base_url and endpoint_env are mutually exclusive"
        raise ConfigError(msg)
    if base_url is not None:
        check_endpoint(base_url, engine=engine)


def resolve_endpoint(
    *,
    base_url: str | None,
    endpoint_env: str | None,
    engine: str,
    environ: Mapping[str, str] | None = None,
) -> str:
    """Return the URL of a service (``base_url`` or the variable ``endpoint_env``), checked.

    Raises:
        ConfigError: Neither is given, the variable is unset or empty (the message names it),
            or the URL breaks the endpoint rules.
    """
    env = os.environ if environ is None else environ
    url = base_url or (env.get(endpoint_env, "") if endpoint_env else "")
    if not url:
        msg = f"environment variable {endpoint_env or '<endpoint_env>'} is not set (profile gpu)"
        raise ConfigError(msg)
    check_endpoint(url, engine=engine)
    return url
