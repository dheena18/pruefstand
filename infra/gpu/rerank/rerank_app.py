"""rerank-cpu: a TEI-compatible ``POST /rerank`` for BAAI/bge-reranker-v2-m3 on the VM CPU (T3.1a).

Wire format (interfaces 1.5, D217):
``POST /rerank {"query": str, "texts": [str, ...], "truncate": true}`` ->
``[{"index": int, "score": float}, ...]`` sorted by score descending; ``GET /health`` -> 200 once
the model is loaded (503 while loading). **No authentication and no secrets** (D217): the service
is reachable only on the internal candidate network, publishes no host port in the executor stack,
and an ``Authorization`` header is neither required nor read. Tier-2 callers send the top 10
passages, truncated to 256 tokens, batched (D222). Standard library HTTP server on purpose: the
only extra dependency in the image is the model library. Query and passages are never logged.
Env: RERANK_MODEL, RERANK_REVISION (HF commit, required), RERANK_WEIGHTS_SHA256 (sha256 of
model.safetensors, checked before the model loads), RERANK_PORT (default 8201), HF_HUB_OFFLINE=1
once the weights are cached.
"""

import hashlib
import importlib
import json
import math
import os
import sys
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, NoReturn, Protocol

MAX_TOKENS_TRUNCATED = 256
MAX_TOKENS_FULL = 512
MAX_TEXTS = 128
MAX_QUERY_CHARS = 2000
SOCKET_TIMEOUT_S = 30
HASH_CHUNK = 1024 * 1024
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


def verify_sha256(path: Path, expected: str) -> None:
    """Raise ``ValueError`` unless the file's sha256 equals ``expected`` (the pinned weights)."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(HASH_CHUNK), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected.lower():
        message = f"sha256 of {path.name} is {digest.hexdigest()}, not the pinned {expected}"
        raise ValueError(message)


def _quota_cpus(root: Path) -> float | None:
    """CPUs granted by the cgroup quota (v2 ``cpu.max``, v1 ``cpu.cfs_*``); None = unlimited."""
    try:
        quota, period = (root / "cpu.max").read_text(encoding="utf-8").split()
        return None if quota == "max" else int(quota) / int(period)
    except (OSError, ValueError, ZeroDivisionError):
        pass
    try:
        v1 = root / "cpu"
        quota_us = int((v1 / "cpu.cfs_quota_us").read_text(encoding="utf-8"))
        period_us = int((v1 / "cpu.cfs_period_us").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return quota_us / period_us if quota_us > 0 and period_us > 0 else None


def cpu_limit(root: Path = Path("/sys/fs/cgroup"), cores: int | None = None) -> int:
    """Threads torch may use: the cgroup CPU quota, capped by the visible cores, at least 1.

    The host has many cores but the container runs under a CFS quota (``cpus:`` in compose); one
    thread per host core is throttled and a two-text rerank took 24 s instead of 0.2 s (D650).
    ``RERANK_THREADS`` overrides the detection.

    >>> cpu_limit(Path("/nonexistent"), cores=160) >= 1
    True
    """
    visible = cores if cores is not None else len(os.sched_getaffinity(0))
    try:
        override = int(os.environ.get("RERANK_THREADS", ""))
    except ValueError:
        override = 0
    if override > 0:
        return min(override, visible)
    quota = _quota_cpus(root)
    return max(1, visible if quota is None else min(visible, math.ceil(quota)))


class CrossEncoderScorer:
    """The real model (sentence-transformers CrossEncoder, CPU, sigmoid scores like TEI)."""

    def __init__(self, model_id: str, revision: str) -> None:
        """Load ``model_id`` at ``revision`` on the CPU (downloads into the HF cache volume)."""
        pinned = os.environ.get("RERANK_WEIGHTS_SHA256", "")
        if pinned:
            hub = importlib.import_module("huggingface_hub")
            weights = hub.hf_hub_download(model_id, "model.safetensors", revision=revision)
            verify_sha256(Path(weights), pinned)
        threads = str(cpu_limit())
        os.environ["OMP_NUM_THREADS"] = os.environ["MKL_NUM_THREADS"] = (
            threads  # before torch loads
        )
        module = importlib.import_module("sentence_transformers")
        importlib.import_module("torch").set_num_threads(int(threads))
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
    if len(query) > MAX_QUERY_CHARS:
        _refuse(413, f"query longer than {MAX_QUERY_CHARS} characters")
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


def _content_length(header: str | None) -> int | None:
    """The declared body length, or ``None`` for a malformed or negative value."""
    try:
        length = int(header or 0)
    except ValueError:
        return None
    return length if length >= 0 else None


def _health(path: str, state: RerankState) -> tuple[int, Any]:
    if path != "/health":
        return 404, {"error": "not found"}
    if state.scorer is None:
        return 503, {"status": "loading"}
    return 200, {"status": "ok"}


def _post_refusal(path: str, length: int | None, state: RerankState) -> tuple[int, Any] | None:
    """The error answer for a POST that must not be read or scored, or ``None`` to go on."""
    if path != "/rerank":
        return 404, {"error": "not found"}
    if length is None:
        return 400, {"error": "invalid Content-Length"}
    if length > MAX_BODY_BYTES:
        return 413, {"error": "body too large"}
    if state.scorer is None:
        return 503, {"error": "model is still loading"}
    return None


def make_server(host: str, port: int, state: RerankState) -> ThreadingHTTPServer:
    """Build the HTTP server (not started); ``port`` 0 picks a free port."""

    class Handler(BaseHTTPRequestHandler):
        timeout = SOCKET_TIMEOUT_S  # a stalled client cannot hold a thread for ever

        def _reply(self, status: int, payload: object) -> None:
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            """``GET /health``: 200 when the model is loaded, 503 while loading."""
            self._reply(*_health(self.path, state))

        def do_POST(self) -> None:
            """``POST /rerank``."""
            length = _content_length(self.headers.get("Content-Length"))
            refusal = _post_refusal(self.path, length, state)
            if refusal is not None:
                self._reply(*refusal)
            elif state.scorer is not None:
                self._reply(*handle_rerank(self.rfile.read(length or 0), state.scorer))

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
