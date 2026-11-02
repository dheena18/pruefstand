"""rerank-cpu: a TEI-compatible ``POST /rerank`` for BAAI/bge-reranker-v2-m3 on the VM CPU (T3.1a).

Wire format (interfaces 1.5, D217):
``POST /rerank {"query": str, "texts": [str, ...], "truncate": true}`` ->
``[{"index": int, "score": float}, ...]`` sorted by score descending; ``GET /health`` -> 200 once
the model is loaded (503 while loading). **No authentication and no secrets** (D217): the service
is reachable only on the internal candidate network, publishes no host port in the executor stack,
and an ``Authorization`` header is neither required nor read. Tier-2 callers send the top 10
passages, truncated to 256 tokens, batched (D222). Standard library HTTP server on purpose: the
only extra dependency in the image is the model library. Query and passages are never logged.
Env: RERANK_MODEL, RERANK_REVISION (HF commit, required), RERANK_PORT (default 8201).
"""

import importlib
import json
import os
import sys
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, NoReturn, Protocol

MAX_TOKENS_TRUNCATED = 256
MAX_TOKENS_FULL = 512
MAX_TEXTS = 128
MAX_BODY_BYTES = 4 * 1024 * 1024
BATCH_SIZE = 8


class Scorer(Protocol):
    """Scores (query, passage) pairs; higher is more relevant."""

    def score(self, query: str, texts: Sequence[str], max_tokens: int) -> list[float]:
        """Return one score per text, each pair cut to ``max_tokens`` tokens."""
        ...


@dataclass
class RerankState:
    """Shared state of the server: the scorer is ``None`` until the model has loaded."""

    scorer: Scorer | None = None


class RequestError(Exception):
    """A request the service refuses; ``status`` is the HTTP status."""

    def __init__(self, status: int, message: str) -> None:
        """Keep the status and the message."""
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class RerankRequest:
    """A validated ``POST /rerank`` body."""

    query: str
    texts: list[str]
    truncate: bool


class CrossEncoderScorer:
    """The real model (sentence-transformers CrossEncoder, CPU, sigmoid scores like TEI)."""

    def __init__(self, model_id: str, revision: str) -> None:
        """Load ``model_id`` at ``revision`` on the CPU (downloads into the HF cache volume)."""
        module = importlib.import_module("sentence_transformers")
        self._model: Any = module.CrossEncoder(
            model_id, revision=revision, device="cpu", max_length=MAX_TOKENS_FULL
        )

    def score(self, query: str, texts: Sequence[str], max_tokens: int) -> list[float]:
        """Score the pairs; the tokenizer cuts every pair at ``max_tokens`` tokens."""
        self._model.max_length = max_tokens
        scores = self._model.predict([(query, t) for t in texts], batch_size=BATCH_SIZE)
        return [float(s) for s in scores]


def _refuse(status: int, message: str) -> NoReturn:
    raise RequestError(status, message)


def parse_request(body: bytes) -> RerankRequest:
    """Validate a body; raises ``RequestError`` (400 not JSON, 413 too many, 422 wrong shape)."""
    try:
        data = json.loads(body)
    except ValueError:
        _refuse(400, "body is not valid JSON")
    if not isinstance(data, dict):
        _refuse(422, "body must be a JSON object")
    query, texts, truncate = data.get("query"), data.get("texts"), data.get("truncate", True)
    if not isinstance(query, str):
        _refuse(422, "query must be a string")
    if not isinstance(texts, list) or not all(isinstance(t, str) for t in texts):
        _refuse(422, "texts must be a list of strings")
    if not isinstance(truncate, bool):
        _refuse(422, "truncate must be a boolean")
    if len(texts) > MAX_TEXTS:
        _refuse(413, f"at most {MAX_TEXTS} texts per request")
    return RerankRequest(query, texts, truncate)


def rank(scores: Sequence[float]) -> list[dict[str, Any]]:
    """TEI response rows ``{"index", "score"}`` sorted by score descending (ties keep input order).

    >>> rank([0.1, 0.9, 0.5])
    [{'index': 1, 'score': 0.9}, {'index': 2, 'score': 0.5}, {'index': 0, 'score': 0.1}]
    """
    order = sorted(range(len(scores)), key=lambda i: (-scores[i], i))
    return [{"index": i, "score": float(scores[i])} for i in order]


def handle_rerank(body: bytes, scorer: Scorer) -> tuple[int, Any]:
    """Answer one ``POST /rerank`` body as ``(status, payload)``; empty ``texts`` -> ``[]``."""
    try:
        request = parse_request(body)
    except RequestError as err:
        return err.status, {"error": str(err)}
    if not request.texts:
        return 200, []
    limit = MAX_TOKENS_TRUNCATED if request.truncate else MAX_TOKENS_FULL
    return 200, rank(scorer.score(request.query, request.texts, limit))


def make_server(host: str, port: int, state: RerankState) -> ThreadingHTTPServer:
    """Build the HTTP server (not started); ``port`` 0 picks a free port."""

    class Handler(BaseHTTPRequestHandler):
        def _reply(self, status: int, payload: object) -> None:
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            """``GET /health``: 200 when the model is loaded, 503 while loading."""
            if self.path != "/health":
                self._reply(404, {"error": "not found"})
            elif state.scorer is None:
                self._reply(503, {"status": "loading"})
            else:
                self._reply(200, {"status": "ok"})

        def do_POST(self) -> None:
            """``POST /rerank``."""
            length = int(self.headers.get("Content-Length") or 0)
            if self.path != "/rerank":
                self._reply(404, {"error": "not found"})
            elif length > MAX_BODY_BYTES:
                self._reply(413, {"error": "body too large"})
            elif state.scorer is None:
                self._reply(503, {"error": "model is still loading"})
            else:
                self._reply(*handle_rerank(self.rfile.read(length), state.scorer))

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            """Never log requests: they carry queries and passages."""

    return ThreadingHTTPServer((host, port), Handler)


def main() -> int:
    """Serve on ``0.0.0.0:$RERANK_PORT``; the model loads in the background (``/health``: 503)."""
    state = RerankState()
    port = int(os.environ.get("RERANK_PORT", "8201"))
    server = make_server("0.0.0.0", port, state)  # noqa: S104  # inside the container
    model = os.environ.get("RERANK_MODEL", "BAAI/bge-reranker-v2-m3")
    revision = os.environ["RERANK_REVISION"]

    def load() -> None:
        state.scorer = CrossEncoderScorer(model, revision)

    threading.Thread(target=load, daemon=True).start()
    server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
