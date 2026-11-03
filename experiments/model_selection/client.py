"""Minimal native-Ollama client for the model benchmark (T3.1b S1).

Talks only to the native endpoints (``NATIVE_PATHS``), never to the OpenAI-compatible ones (Y3.1,
D219). Every chat request carries ``think: false`` and exactly the catalogue ``options`` of the
model (Y3.2, D220); the benchmark never sets a residency time. Model ids in results are
``ollama/<tag>``; the bare tag is only in bodies.
"""

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import yaml

REPO = Path(__file__).resolve().parents[2]
MODELS_YAML = REPO / "infra" / "gpu" / "models.yaml"
NATIVE_PATHS = {
    "chat": "/api/chat",
    "embed": "/api/embed",
    "ps": "/api/ps",
    "tags": "/api/tags",
    "show": "/api/show",
    "version": "/api/version",
}
DEFAULT_URL = "http://127.0.0.1:11434"
NS = 1e9


class BenchError(RuntimeError):
    """A request to the Ollama server failed."""


@dataclass(frozen=True)
class Entry:
    """One catalogue model.

    ``id`` (``ollama/<tag>``), bare ``tag``, ``options`` and embed prefixes.
    """

    id: str
    tag: str
    options: dict[str, Any]
    role: str
    query_prefix: str = ""
    doc_prefix: str = ""


@dataclass(frozen=True)
class ChatResult:
    """One finished chat call with the server-reported counts and the client-measured timings."""

    content: str
    thinking: str
    prompt_eval_count: int
    eval_count: int
    load_duration_s: float
    ttft_s: float
    wall_s: float
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


def load_entry(model: str, path: Path = MODELS_YAML) -> Entry:
    """Return the catalogue entry for an id (``ollama/<tag>``) or bare tag.

    Raises ``KeyError`` when unknown.
    """
    for m in yaml.safe_load(path.read_text(encoding="utf-8"))["models"]:
        if model in (m["id"], m["tag"]):
            return Entry(
                m["id"],
                m["tag"],
                dict(m["options"]),
                m["role"],
                m.get("query_prefix", ""),
                m.get("doc_prefix", ""),
            )
    raise KeyError(model)


def build_chat_body(
    entry: Entry,
    messages: list[dict[str, str]],
    fmt: dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the ``/api/chat`` body.

    Catalogue options (``options`` only for the load/KV measurements), thinking off.
    """
    body: dict[str, Any] = {
        "model": entry.tag,
        "messages": messages,
        "stream": True,
        "think": False,
        "options": dict(options if options is not None else entry.options),
    }
    if fmt is not None:
        body["format"] = fmt
    return body


def build_embed_body(entry: Entry, texts: list[str], kind: str = "doc") -> dict[str, Any]:
    """Build the ``/api/embed`` body with the e5-style prefix of ``kind`` (``query`` or ``doc``)."""
    prefix = entry.query_prefix if kind == "query" else entry.doc_prefix
    return {
        "model": entry.tag,
        "input": [prefix + t for t in texts],
        "options": dict(entry.options),
    }


def parse_final(
    obj: dict[str, Any], content: str, thinking: str, ttft_s: float, wall_s: float
) -> ChatResult:
    """Turn the last streamed chunk (``done: true``) into a ``ChatResult``."""
    return ChatResult(
        content=content,
        thinking=thinking,
        prompt_eval_count=int(obj.get("prompt_eval_count", 0)),
        eval_count=int(obj.get("eval_count", 0)),
        load_duration_s=float(obj.get("load_duration", 0)) / NS,
        ttft_s=ttft_s,
        wall_s=wall_s,
        raw=obj,
    )


class OllamaClient:
    """HTTP client for one Ollama lane.

    ``base_url`` defaults to ``$OLLAMA_GPU0_URL``/``$OLLAMA_GPU1_URL``.
    """

    def __init__(
        self, base_url: str | None = None, lane: str = "GPU0", timeout_s: float = 900.0
    ) -> None:
        url = base_url or os.environ.get(f"OLLAMA_{lane}_URL", DEFAULT_URL)
        self._http = httpx.Client(base_url=url, timeout=httpx.Timeout(timeout_s, connect=10.0))

    def chat(
        self,
        entry: Entry,
        messages: list[dict[str, str]],
        fmt: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
    ) -> ChatResult:
        """Stream one chat call; ``ttft_s`` is the time to the first content or thinking chunk."""
        body = build_chat_body(entry, messages, fmt, options)
        start, ttft, parts, think, final = time.perf_counter(), 0.0, [], [], {}
        try:
            with self._http.stream("POST", NATIVE_PATHS["chat"], json=body) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line:
                        continue
                    obj = json.loads(line)
                    msg = obj.get("message", {})
                    if (msg.get("content") or msg.get("thinking")) and not ttft:
                        ttft = time.perf_counter() - start
                    parts.append(msg.get("content") or "")
                    think.append(msg.get("thinking") or "")
                    if obj.get("done"):
                        final = obj
        except (httpx.HTTPError, ValueError) as exc:
            msg = f"chat {entry.id} failed: {type(exc).__name__}"
            raise BenchError(msg) from exc
        return parse_final(final, "".join(parts), "".join(think), ttft, time.perf_counter() - start)

    def embed(self, entry: Entry, texts: list[str], kind: str = "doc") -> list[list[float]]:
        """Return one vector per text from ``/api/embed``."""
        try:
            resp = self._http.post(NATIVE_PATHS["embed"], json=build_embed_body(entry, texts, kind))
            resp.raise_for_status()
            vectors: list[list[float]] = resp.json()["embeddings"]
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            msg = f"embed {entry.id} failed: {type(exc).__name__}"
            raise BenchError(msg) from exc
        return vectors

    def get(self, name: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        """Call a read-only native endpoint (``ps``, ``show``, ``version``)."""
        try:
            resp = (
                self._http.post(NATIVE_PATHS[name], json=body)
                if body
                else self._http.get(NATIVE_PATHS[name])
            )
            resp.raise_for_status()
            payload: dict[str, Any] = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            msg = f"{name} failed: {type(exc).__name__}"
            raise BenchError(msg) from exc
        return payload
