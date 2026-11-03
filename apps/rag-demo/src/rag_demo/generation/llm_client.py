"""The two small httpx chat clients behind one protocol (T3.6, D216, D219).

``OpenAICompatClient`` talks to llama.cpp (tier 1, ``/v1/chat/completions``), ``OllamaChatClient``
to Ollama's native ``/api/chat`` (tier 2; never ``/v1``, never ``keep_alive``). Both send the
bearer key named by ``generator.api_key_env`` when it is set (read once, never logged, never part
of an error) and retry a loading or overloaded server (HTTP 502/503/504, connection errors) twice.
A read timeout is not retried: the generator serialises requests, so a request legitimately waits
in a queue (TTFT p95 32 s at 4 and 70 s at 8 parallel streams) and a retry would only add load.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from rag_demo.auth import auth_headers
from rag_demo.errors import GenerationError
from rag_demo.models import RagConfig

_log = logging.getLogger(__name__)
RETRY_STATUS = frozenset({502, 503, 504})
RETRIES = 2
BACKOFF_S = (1.0, 3.0)
CONNECT_TIMEOUT_S = 10.0


@dataclass(frozen=True)
class ChatReply:
    """What a chat call returns: raw text, served model and the engine's token usage."""

    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int


class ChatClient(Protocol):
    """One chat completion against an engine."""

    async def chat(self, messages: list[dict[str, str]]) -> ChatReply:
        """Send ``messages`` and return the reply.

        Raises:
            GenerationError: Unreachable server, HTTP error, timeout or unexpected response shape.
        """
        ...


def build_chat_request(messages: list[dict[str, str]], cfg: RagConfig) -> dict[str, Any]:
    """Build the llama.cpp chat body (greedy, seeded, thinking off for Qwen3)."""
    body: dict[str, Any] = {
        "model": cfg.generator.model,
        "messages": messages,
        "temperature": cfg.generator.temperature,
        "seed": cfg.generator.seed,
        "max_tokens": cfg.max_tokens,
        "stream": False,
    }
    if cfg.generator.family.startswith("qwen3"):
        body["chat_template_kwargs"] = {"enable_thinking": cfg.generator.enable_thinking}
    return body


def build_ollama_request(messages: list[dict[str, str]], cfg: RagConfig) -> dict[str, Any]:
    """Build the ``/api/chat`` body: bare tag, ``think: false``, load-time and sampling options.

    ``options`` = the config's catalogue-checked ``num_ctx``/``top_p`` plus ``temperature``,
    ``seed`` and ``num_predict`` (= ``generation.max_tokens``) from ``generation`` (R12 N2).
    There is never a ``keep_alive`` (model loading is the orchestrator's job).

    Raises:
        GenerationError: The config has no ``generation`` section (not an Ollama profile).
    """
    gen = cfg.generation
    if gen is None:
        msg = "engine ollama needs the generation section"
        raise GenerationError(msg)
    return {
        "model": cfg.generator.model,
        "messages": messages,
        "think": cfg.generator.enable_thinking,
        "stream": False,
        "options": {
            **cfg.generator.options,
            "temperature": gen.temperature,
            "seed": gen.seed,
            "num_predict": gen.max_tokens,
        },
    }


class _HttpChatClient:
    """Shared POST, auth header, retry and error mapping; subclasses fix path, body and parsing."""

    PATH = ""

    def __init__(
        self,
        cfg: RagConfig,
        base_url: str,
        *,
        client: httpx.AsyncClient | None = None,
        timeout_s: float = 180.0,
    ) -> None:
        self._cfg = cfg
        self._url = f"{base_url.rstrip('/')}{self.PATH}"
        self._headers = auth_headers(cfg.generator.api_key_env)  # read once, never logged
        timeout = httpx.Timeout(timeout_s, connect=CONNECT_TIMEOUT_S)
        self._client = client or httpx.AsyncClient(timeout=timeout)

    def _body(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        raise NotImplementedError

    def _parse(self, data: dict[str, Any]) -> ChatReply:
        raise NotImplementedError

    async def chat(self, messages: list[dict[str, str]]) -> ChatReply:
        """Send ``messages`` and return the parsed reply (see ``ChatClient``)."""
        body = self._body(messages)
        for attempt in range(RETRIES + 1):
            retry = attempt < RETRIES
            try:
                resp = await self._client.post(self._url, json=body, headers=self._headers)
            except (httpx.ConnectError, httpx.ConnectTimeout) as err:
                if not retry:
                    msg = f"generator unreachable ({type(err).__name__})"
                    raise GenerationError(msg) from None
            except httpx.HTTPError as err:
                msg = f"generator unreachable ({type(err).__name__})"
                raise GenerationError(msg) from None
            else:
                if resp.status_code == 200:
                    return self._parse_response(resp)
                if resp.status_code not in RETRY_STATUS or not retry:
                    msg = f"generator returned HTTP {resp.status_code}"
                    raise GenerationError(msg)
            _log.warning("generator not ready, retry %d of %d", attempt + 1, RETRIES)
            await asyncio.sleep(BACKOFF_S[min(attempt, len(BACKOFF_S) - 1)])
        msg = "generator retries exhausted"  # unreachable: the last attempt raises above
        raise GenerationError(msg)

    def _parse_response(self, resp: httpx.Response) -> ChatReply:
        try:
            data: dict[str, Any] = resp.json()
            return self._parse(data)
        except (ValueError, KeyError, IndexError, TypeError, AttributeError):
            msg = "generator response has an unexpected shape"
            raise GenerationError(msg) from None


class OpenAICompatClient(_HttpChatClient):
    """llama.cpp (tier 1): ``POST /v1/chat/completions``; thinking off via the chat template."""

    PATH = "/v1/chat/completions"

    def _body(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        return build_chat_request(messages, self._cfg)

    def _parse(self, data: dict[str, Any]) -> ChatReply:
        usage = data.get("usage") or {}
        return ChatReply(
            text=str(data["choices"][0]["message"]["content"]),
            model=str(data.get("model") or self._cfg.generator.model),
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
        )


class OllamaChatClient(_HttpChatClient):
    """Ollama (tier 2): native ``POST /api/chat``, ``think: false``, catalogue + sampling opts."""

    PATH = "/api/chat"

    def _body(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        return build_ollama_request(messages, self._cfg)

    def _parse(self, data: dict[str, Any]) -> ChatReply:
        return ChatReply(
            text=str(data["message"]["content"]),
            model=str(data.get("model") or self._cfg.generator.model),
            prompt_tokens=int(data.get("prompt_eval_count", 0)),
            completion_tokens=int(data.get("eval_count", 0)),
        )
