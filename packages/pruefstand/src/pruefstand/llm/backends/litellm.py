"""The one place that imports ``litellm`` (import-linter contract ``llm-gateway``, ADR-0009).

Providers: ``openai_compatible_local/<m>`` (llama.cpp, LiteLLM ``openai/``), ``github/<m>`` (GitHub
Models) and ``ollama/<tag>`` (LiteLLM ``ollama_chat/``, native ``/api/chat``, options from the
catalogue). Pure request building lives in ``kwargs.py``; this module makes the calls.
"""

import asyncio
import os
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
from litellm.llms.custom_httpx.http_handler import AsyncHTTPHandler

from pruefstand.core.errors import ConfigError, LLMError
from pruefstand.core.models.llm import LLMRequest, LLMResponse
from pruefstand.core.models.target import Usage
from pruefstand.llm.backends import versions
from pruefstand.llm.backends.kwargs import (
    completion_kwargs,
    litellm_model,
    provider_prefix,
    strip_think,
)
from pruefstand.llm.backends.limits import IDENTITY_HEADERS, LimitedTransport, response_limits
from pruefstand.llm.providers import catalogue_options
from pruefstand.llm.retry import RateLimitedError, parse_retry_after

if litellm.litellm_mode != "PRODUCTION":  # litellm was imported first, in DEV mode, and loaded .env
    msg = "litellm was imported before pruefstand.llm in non-PRODUCTION mode (.env may be loaded)"
    raise ConfigError(msg)
litellm.suppress_debug_info = True
litellm.telemetry = False
litellm.drop_params = False

__all__ = [
    "GITHUB_MODELS_URL",
    "NO_KEY",
    "LiteLLMBackend",
    "completion_kwargs",
    "litellm_model",
    "map_error",
    "provider_prefix",
    "strip_think",
]

GITHUB_MODELS_URL = (
    "https://models.github.ai/inference"  # LiteLLM's own default host does not resolve
)
NO_KEY = "not-needed"  # llama.cpp ignores the key; the OpenAI client insists on a non-empty one
_CONNECTION_ERRORS = ("APIConnectionError", "Timeout", "APITimeoutError")
_TRANSIENT_STATUS = frozenset({408, 409, 425, 429})
_MAX_ERROR_TEXT = 200


class LiteLLMBackend:
    """Real model calls through LiteLLM; implements ``LLMBackend``.

    Args:
        model_id: Provider-qualified model this backend was built for; requests for another
            model of the same provider are served with the same endpoint.
        api_base: Endpoint (llama.cpp, Ollama); None = LiteLLM's default for the provider.
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

    async def resolve_version(self, model: str) -> str | None:
        """Return the provider-reported version of ``model`` for the cache key, or None.

        Ollama: tag + manifest digest from ``/api/tags``; llama.cpp: hash of the model path from
        ``/props``; GitHub Models: None (the version arrives with each response).

        Raises:
            LLMError: The probe failed (transient).
        """
        provider = provider_prefix(model)
        if self.api_base is None or provider not in {"ollama", "openai_compatible_local"}:
            return None
        try:
            if provider == "ollama":
                return await asyncio.to_thread(versions.ollama_version, self.api_base, model)
            return await asyncio.to_thread(versions.llamacpp_version, self.api_base)
        except ConfigError:
            raise
        except Exception as err:  # best effort: the call that follows reports a real outage
            msg = f"{provider}: version probe failed ({type(err).__name__})"
            raise LLMError(msg, transient=True) from None

    async def acomplete(self, req: LLMRequest) -> LLMResponse:
        """Call the model once.

        Args:
            req: The request.

        Returns:
            The response with usage, ``cost_usd`` (0.0, free providers only), ``latency_ms``.

        Raises:
            LLMError: Timeout, connection loss, 429 and 5xx are ``transient=True`` (a 429 is a
                ``RateLimitedError`` that carries ``Retry-After``); other 4xx, a missing key or a
                foreign provider are not.
            ConfigError: An ``ollama/`` model is missing from the GPU catalogue (checked now,
                not when the backend was built).
        """
        provider = provider_prefix(req.model)
        if provider != provider_prefix(self.model_id):
            msg = f"backend for '{provider_prefix(self.model_id)}' cannot serve model '{req.model}'"
            raise LLMError(msg, transient=False)
        options = catalogue_options(req.model) if provider == "ollama" else None
        key = self._api_key()
        kwargs = completion_kwargs(
            req, api_base=self.api_base, api_key=key, timeout_s=self.timeout_s, options=options
        )
        asked = (
            req.max_tokens if options is None else max(req.max_tokens, int(options["num_predict"]))
        )
        max_chars, max_bytes = response_limits(asked)
        tripped: list[bool] = []
        http_client = self._bounded_client(provider, key, max_bytes, tripped, kwargs)
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

    def _bounded_client(
        self,
        provider: str,
        key: str,
        max_bytes: int,
        tripped: list[bool],
        kwargs: dict[str, object],
    ) -> httpx.AsyncClient | None:
        """Install a size-capped HTTP client (OpenAI SDK, or a LiteLLM handler for Ollama)."""
        base = self.api_base or (GITHUB_MODELS_URL if provider == "github" else None)
        if provider not in {"openai_compatible_local", "github", "ollama"} or base is None:
            return None
        transport = LimitedTransport(max_bytes, tripped)
        http_client = httpx.AsyncClient(
            transport=transport, timeout=self.timeout_s, headers=IDENTITY_HEADERS
        )
        if provider == "ollama":
            handler = AsyncHTTPHandler(timeout=self.timeout_s)
            handler.client = http_client
            kwargs["client"] = handler
            return http_client
        kwargs["client"] = openai.AsyncOpenAI(
            base_url=base,
            api_key=key,
            http_client=http_client,
            max_retries=0,
            default_headers=IDENTITY_HEADERS,
        )
        return http_client

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
            reasoning = getattr(raw.choices[0].message, "reasoning_content", None)
            self.think_stripped += int(stripped or bool(reasoning))  # LiteLLM may split it already
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


def _retry_after(err: Exception) -> float | None:
    """Read ``Retry-After`` (seconds) from the first response in the exception chain.

    LiteLLM wraps the SDK error in its own and drops the headers; the original response is
    still on the chained exceptions.
    """
    seen: set[int] = set()
    cur: BaseException | None = err
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        headers = getattr(getattr(cur, "response", None), "headers", None)
        if headers is not None:
            try:
                value = parse_retry_after(headers.get("retry-after"))
            except (AttributeError, TypeError):
                value = None
            if value is not None:
                return value
        cur = cur.__cause__ or cur.__context__
    return None


def map_error(err: Exception, provider: str, key: str) -> LLMError:
    """Map a LiteLLM/OpenAI exception to ``LLMError``; the key never appears in the text.

    Connection problems (DNS, refused, reset, timeout) are transient and carry no status; so are
    408/409/425/429 and 5xx. A 429 becomes a ``RateLimitedError`` with the ``Retry-After`` the
    provider sent. Any other exception without a status is permanent.
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
    text = f"{provider}: {where}: {detail}"
    if status == 429:
        return RateLimitedError(text, retry_after_s=_retry_after(err))
    return LLMError(text, transient=transient, status=status)
