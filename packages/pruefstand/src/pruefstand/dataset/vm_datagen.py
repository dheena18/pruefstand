"""The VM CPU datagen model as a backend (D1200, D1201): served-model check and backend.

The VM model (``scripts/models/vm_llm.sh``) is a one-slot CPU server, about 70 s per call. It is
reached at ``PRUEFSTAND_DATAGEN_BASE_URL`` (default ``http://127.0.0.1:18091/v1``), never at the
judge URL, so a batch cannot land on the tier-1 llama.cpp judge/generator by mistake; and before
any call ``check_vm_served`` asks ``/models`` which alias the server serves (llama-server echoes
the requested model name in its answers, so the answer itself proves nothing).
"""

from urllib.parse import urlsplit

import httpx

from pruefstand.core.config import ModelRef
from pruefstand.core.errors import ConfigError
from pruefstand.llm.backends.litellm import LiteLLMBackend

VM_PROVIDER = "openai_compatible_local"
VM_TIMEOUT_S = 900.0  # one slot, about 70 s per call; queued requests wait for the one before
_LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})
_START = "start it with scripts/models/vm_llm.sh start (URL: PRUEFSTAND_DATAGEN_BASE_URL)"


def vm_alias(model_id: str) -> str:
    """The alias the VM server serves for a pinned id (the part after the provider).

    >>> vm_alias("openai_compatible_local/ministral-3-14b-instruct-2512")
    'ministral-3-14b-instruct-2512'
    """
    return model_id.split("/", 1)[1]


def _loopback(base_url: str) -> str:
    host = urlsplit(base_url).hostname or ""
    if urlsplit(base_url).scheme != "http" or host not in _LOOPBACK:
        msg = f"the VM datagen URL must be http on the loopback interface, got {base_url!r} (D850)"
        raise ConfigError(msg)
    return base_url.rstrip("/")


def check_vm_served(model_id: str, base_url: str, timeout_s: float = 10.0) -> None:
    """Refuse unless the server at ``base_url`` serves the alias of ``model_id``.

    Args:
        model_id: A pinned VM id (``openai_compatible_local/<alias>``).
        base_url: The OpenAI-compatible base URL (``.../v1``), loopback only.
        timeout_s: Timeout of the ``/models`` request.

    Raises:
        ConfigError: Not loopback, no answer, or another model is served.
    """
    url = _loopback(base_url)
    try:
        resp = httpx.get(f"{url}/models", timeout=timeout_s)
        resp.raise_for_status()
        served = [str(m["id"]) for m in resp.json()["data"]]
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        msg = f"the VM datagen model at {url} does not answer ({type(exc).__name__}); {_START}"
        raise ConfigError(msg) from exc
    if vm_alias(model_id) not in served:
        msg = f"{url} serves {served}, not {vm_alias(model_id)} (D1201); {_START}"
        raise ConfigError(msg)


def build_vm_backend(ref: ModelRef, base_url: str) -> LiteLLMBackend:
    """The backend of a pinned VM model at ``base_url`` (checked first), with ``VM_TIMEOUT_S``.

    Raises:
        ConfigError: As ``check_vm_served``.
    """
    check_vm_served(ref.id, base_url)
    return LiteLLMBackend(
        ref.id, api_base=_loopback(base_url), api_key_env=None, timeout_s=VM_TIMEOUT_S
    )
