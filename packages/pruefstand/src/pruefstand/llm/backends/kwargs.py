"""Pure request building for LiteLLM: model-id translation, thinking off, Ollama options.

Nothing here imports ``litellm`` or ``openai`` (import-linter contract ``llm-gateway``); the
backend module imports these helpers and does the calls.
"""

import re
from collections.abc import Mapping

from pruefstand.core.config import ModelRef
from pruefstand.core.errors import ConfigError
from pruefstand.core.logging import get_logger
from pruefstand.core.models.llm import LLMRequest

_log = get_logger(__name__)
_THINK_BLOCK = re.compile(r"\A\s*<think>.*?</think>\s*", re.DOTALL)


def provider_prefix(model_id: str) -> str:
    """Return the provider prefix of ``model_id``."""
    return model_id.split("/", 1)[0]


def _litellm_id(model_id: str) -> str:
    """Translate a config id into LiteLLM's model string (R11 D219/D221)."""
    for prefix in ("ollama_chat/", "openai/"):
        if model_id.startswith(prefix):
            msg = (
                f"model id '{model_id}': the prefix '{prefix}' is a LiteLLM detail, "
                "not a config value; use ollama/<tag> or openai_compatible_local/<m> (D221)"
            )
            raise ConfigError(msg)
    provider, _, rest = model_id.partition("/")
    if provider == "ollama":
        return f"ollama_chat/{rest}"
    if provider == "openai_compatible_local":
        return f"openai/{rest}"
    return model_id


def litellm_model(ref: ModelRef) -> str:
    """Return LiteLLM's model string for ``ref`` (the only translation point, D221).

    Examples:
        >>> litellm_model(ModelRef(id="ollama/qwen3.8:27b-q8_0", family="qwen"))
        'ollama_chat/qwen3.8:27b-q8_0'
        >>> litellm_model(ModelRef(id="openai_compatible_local/m", family="qwen"))
        'openai/m'

    Raises:
        ConfigError: ``ref.id`` already carries a LiteLLM prefix (``ollama_chat/``, ``openai/``).
    """
    return _litellm_id(ref.id)


def strip_think(text: str) -> tuple[str, bool]:
    """Remove a leading ``<think>...</think>`` block.

    Returns:
        ``(text, stripped)``; a block that is not closed or not leading is left alone.

    Examples:
        >>> strip_think("<think>x</think>Antwort")
        ('Antwort', True)
        >>> strip_think("Antwort")
        ('Antwort', False)
    """
    stripped, count = _THINK_BLOCK.subn("", text, count=1)
    return (stripped, True) if count else (text, False)


def _ollama_kwargs(req: LLMRequest, options: Mapping[str, float]) -> dict[str, object]:
    """Native ``/api/chat`` arguments: the catalogue options win over the caller's (Y3.2)."""
    asked = {"temperature": req.temperature, "num_predict": req.max_tokens, "seed": req.seed}
    for key, value in asked.items():
        if value is not None and value != options[key]:
            _log.debug("ollama_option_replaced", option=key, asked=value, used=options[key])
    return {
        "temperature": options["temperature"],
        "max_tokens": int(options["num_predict"]),
        "seed": int(options["seed"]),
        "top_p": options["top_p"],
        "num_ctx": int(options["num_ctx"]),
        "think": False,  # D95: thinking is off in every tier and role
    }


def completion_kwargs(
    req: LLMRequest,
    *,
    api_base: str | None,
    api_key: str,
    timeout_s: float,
    options: Mapping[str, float] | None = None,
) -> dict[str, object]:
    """Build the ``litellm.acompletion`` arguments for ``req`` (pure).

    Qwen3 ids on the OpenAI-compatible llama.cpp path always send
    ``chat_template_kwargs.enable_thinking=false`` (D95). ``ollama/`` ids go to the native
    ``/api/chat`` (LiteLLM ``ollama_chat``) with the catalogue ``options`` and ``think=false``;
    no ``keep_alive`` is ever sent. Retries stay at 0: the client owns them.

    Args:
        req: The request.
        api_base: Endpoint, or None for LiteLLM's default of the provider.
        api_key: The key (``NO_KEY`` for local providers).
        timeout_s: Hard timeout.
        options: Catalogue options of an ``ollama/`` model (required for that provider).

    Raises:
        ConfigError: ``req.model`` carries a LiteLLM prefix (D221), or an ``ollama/`` model comes
            without options.
    """
    provider = provider_prefix(req.model)
    kwargs: dict[str, object] = {
        "model": _litellm_id(req.model),
        "messages": [{"role": m.role, "content": m.content} for m in req.messages],
        "temperature": req.temperature,
        "max_tokens": req.max_tokens,
        "timeout": timeout_s,
        "num_retries": 0,
        "api_key": api_key,
    }
    if req.seed is not None:
        kwargs["seed"] = req.seed
    if api_base is not None:
        kwargs["api_base"] = api_base
    if req.response_format == "json":
        kwargs["response_format"] = {"type": "json_object"}
    if provider == "ollama" and req.json_schema is not None:
        # LiteLLM's ollama_chat turns json_schema into the native `format` (grammar-constrained)
        kwargs["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": req.prompt_id, "schema": req.json_schema},
        }
    if provider == "ollama":
        if options is None:
            msg = f"model '{req.model}': Ollama options from the catalogue are required"
            raise ConfigError(msg)
        kwargs.update(_ollama_kwargs(req, options))
    if provider == "openai_compatible_local" and "qwen3" in req.model.lower():
        kwargs["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
    return kwargs
