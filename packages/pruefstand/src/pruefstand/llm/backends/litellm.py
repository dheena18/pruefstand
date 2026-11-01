"""The one place that imports ``litellm`` (import-linter contract ``llm-gateway``, ADR-0009).

Providers: ``openai_compatible_local/<m>`` (llama.cpp, LiteLLM ``openai/``), ``github/<m>`` (GitHub
Models) and, from T5.1, ``ollama/<tag>`` (LiteLLM ``ollama_chat/``, native ``/api/chat``).
"""

import asyncio
import os
import re
import time
from typing import Any

# LiteLLM reads its model-cost map at import time; the packaged copy keeps imports offline
# (CLAUDE.md §3). Outside PRODUCTION mode its __init__ runs dotenv.load_dotenv(), which would pull
# the repository .env (every secret) into this process and its children (CLAUDE.md §5).
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
os.environ["LITELLM_MODE"] = "PRODUCTION"  # forced: an exported DEV must not win

import httpx
import litellm
import openai

from pruefstand.core.config import ModelRef
from pruefstand.core.errors import ConfigError, LLMError
from pruefstand.core.models.llm import LLMRequest, LLMResponse
from pruefstand.core.models.target import Usage
from pruefstand.llm.backends.limits import LimitedTransport, response_limits

if litellm.litellm_mode != "PRODUCTION":  # litellm was imported first, in DEV mode, and loaded .env
    msg = "litellm was imported before pruefstand.llm in non-PRODUCTION mode (.env may be loaded)"
    raise ConfigError(msg)
litellm.suppress_debug_info = True
litellm.telemetry = False
litellm.drop_params = False

GITHUB_MODELS_URL = (
    "https://models.github.ai/inference"  # LiteLLM's own default host does not resolve
)
NO_KEY = "not-needed"  # llama.cpp ignores the key; the OpenAI client insists on a non-empty one
_THINK_BLOCK = re.compile(r"\A\s*<think>.*?</think>\s*", re.DOTALL)
_CONNECTION_ERRORS = ("APIConnectionError", "Timeout", "APITimeoutError")
_TRANSIENT_STATUS = frozenset({408, 409, 425, 429})
_MAX_ERROR_TEXT = 200


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


def completion_kwargs(
    req: LLMRequest, *, api_base: str | None, api_key: str, timeout_s: float
) -> dict[str, object]:
    """Build the ``litellm.acompletion`` arguments for ``req`` (pure).

    Qwen3 ids on the OpenAI-compatible llama.cpp path always send
    ``chat_template_kwargs.enable_thinking=false`` (D95). Retries stay at 0: the client owns them.

    Raises:
        ConfigError: ``req.model`` carries a LiteLLM prefix (D221).
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
    if req.response_format == "json" and provider != "ollama":
        kwargs["response_format"] = {"type": "json_object"}
    if provider == "openai_compatible_local" and "qwen3" in req.model.lower():
        kwargs["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
    return kwargs


class LiteLLMBackend:
    """Real model calls through LiteLLM; implements ``LLMBackend``.

    Args:
        model_id: Provider-qualified model this backend was built for; requests for another
            model of the same provider are served with the same endpoint.
        api_base: Endpoint (llama.cpp); None = LiteLLM's default for the provider.
        api_key_env: Name of the environment variable that holds the key; read at call time,
            never stored, logged or put into an exception. None = no key needed.
        timeout_s: Hard timeout per call in seconds.

    Attributes:
        think_stripped: Number of answers whose leading ``<think>`` block was removed.
    """

    def __init__(
        self, model_id: str, api_base: str | None, api_key_env: str | None, timeout_s: float
    ) -> None:
        self.model_id = model_id
        self.api_base = api_base
        self.api_key_env = api_key_env
        self.timeout_s = timeout_s
        self.think_stripped = 0

    def _api_key(self) -> str:
        if self.api_key_env is None:
            return NO_KEY
        value = os.environ.get(self.api_key_env)
        if not value:
            msg = f"environment variable {self.api_key_env} is not set"
            raise LLMError(msg, transient=False)
        return value

    async def acomplete(self, req: LLMRequest) -> LLMResponse:
        """Call the model once.

        Args:
            req: The request.

        Returns:
            The response with usage, ``cost_usd`` (0.0, free providers only), ``latency_ms``.

        Raises:
            LLMError: Timeout, connection loss, 429 and 5xx are ``transient=True``; other 4xx,
                a missing key or a foreign provider are not.
        """
        provider = provider_prefix(req.model)
        if provider != provider_prefix(self.model_id):
            msg = f"backend for '{provider_prefix(self.model_id)}' cannot serve model '{req.model}'"
            raise LLMError(msg, transient=False)
        key = self._api_key()
        kwargs = completion_kwargs(
            req, api_base=self.api_base, api_key=key, timeout_s=self.timeout_s
        )
        max_chars, max_bytes = response_limits(req.max_tokens)
        tripped: list[bool] = []
        http_client: httpx.AsyncClient | None = None
        base = self.api_base or (GITHUB_MODELS_URL if provider == "github" else None)
        # Every provider that goes through the OpenAI client gets the bounded transport. `ollama/`
        # (T5.1) must install the same LimitedTransport on its httpx client before it is enabled.
        if provider in {"openai_compatible_local", "github"} and base is not None:
            http_client = httpx.AsyncClient(
                transport=LimitedTransport(max_bytes, tripped), timeout=self.timeout_s
            )
            kwargs["client"] = openai.AsyncOpenAI(
                base_url=base, api_key=key, http_client=http_client, max_retries=0
            )
        start = time.perf_counter()
        try:
            raw = await asyncio.wait_for(litellm.acompletion(**kwargs), timeout=self.timeout_s)
        except TimeoutError:
            msg = f"{provider}: timeout after {self.timeout_s:g} s"
            raise LLMError(msg, transient=True) from None
        except Exception as err:
            if tripped:
                msg = f"{provider}: response too large (limit {max_bytes} bytes)"
                raise LLMError(msg, transient=False) from None
            raise map_error(err, provider, key) from None
        finally:
            if http_client is not None:
                await http_client.aclose()
        latency_ms = (time.perf_counter() - start) * 1000
        return self._to_response(raw, req, provider, latency_ms, max_chars)

    def _to_response(
        self,
        raw: Any,  # noqa: ANN401  (LiteLLM's response union is untyped at the attribute level)
        req: LLMRequest,
        provider: str,
        latency_ms: float,
        max_chars: int,
    ) -> LLMResponse:
        if not raw.choices:
            msg = f"{provider}: the answer holds no choices"
            raise LLMError(msg, transient=True)
        text = raw.choices[0].message.content or ""
        if len(text) > max_chars:
            msg = (
                f"{provider}: response too large "
                f"({len(text)} characters, max_tokens={req.max_tokens})"
            )
            raise LLMError(msg, transient=False)
        if "qwen3" in req.model.lower():
            text, stripped = strip_think(text)
            self.think_stripped += int(stripped)
        usage = raw.usage
        return LLMResponse(
            text=text,
            model=req.model,
            usage=Usage(
                prompt_tokens=int(usage.prompt_tokens or 0),
                completion_tokens=int(usage.completion_tokens or 0),
            ),
            cost_usd=0.0,
            latency_ms=latency_ms,
            cached=False,
            provider=provider,
            model_version=str(raw.model) if provider == "github" and raw.model else None,
        )


def _root_connection_error(err: BaseException) -> BaseException | None:
    """Return the connection-level exception in the cause/context chain of ``err``, if any."""
    seen: set[int] = set()
    stack: list[BaseException | None] = [err]
    while stack:
        cur = stack.pop()
        if cur is None or id(cur) in seen:
            continue
        seen.add(id(cur))
        if (
            isinstance(cur, httpx.TransportError | openai.APIConnectionError | OSError)
            or type(cur).__name__ in _CONNECTION_ERRORS
        ):
            return cur
        stack += [cur.__cause__, cur.__context__]
    return None


def map_error(err: Exception, provider: str, key: str) -> LLMError:
    """Map a LiteLLM/OpenAI exception to ``LLMError``; the key never appears in the text.

    Connection problems (DNS, refused, reset, timeout) are transient and carry no status; so are
    408/409/425/429 and 5xx. Any other exception without a status is permanent.
    """
    root = _root_connection_error(err)
    if root is not None:
        kind = "host not found" if "gaierror" in type(root).__name__ else type(root).__name__
        return LLMError(f"{provider}: connection error ({kind})", transient=True)
    raw_status = getattr(err, "status_code", None)
    status = raw_status if isinstance(raw_status, int) else None
    transient = status is not None and (status >= 500 or status in _TRANSIENT_STATUS)
    detail = str(err).replace(key, "***")[:_MAX_ERROR_TEXT]
    where = f"HTTP {status}" if status is not None else type(err).__name__
    return LLMError(f"{provider}: {where}: {detail}", transient=transient, status=status)
