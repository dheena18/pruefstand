"""Scripted loopback server: replays a list of HTTP answers, records every request.

Real sockets, no model behind it. It serves the OpenAI chat wire format (``/v1/chat/completions``)
and the Ollama native API (``/api/chat``, ``/api/tags``) so that tests can inspect request shape,
retry behaviour and header handling of the real backend.
"""

import json
import threading
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from testsupport.loopback import completion_json


@dataclass
class Step:
    """One scripted answer."""

    status: int = 200
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes | None = None
    delay_s: float = 0.0


@dataclass
class Seen:
    """What the server received."""

    path: str
    body: dict[str, object]
    method: str = "POST"


@dataclass
class ScriptState:
    steps: list[Step]
    seen: list[Seen] = field(default_factory=list)
    tags: Mapping[str, object] = field(default_factory=dict)
    content: str = "OK"
    model_name: str = "loop"
    lock: threading.Lock = field(default_factory=threading.Lock)

    def posts(self) -> int:
        """Number of POST requests seen (version probes are GETs)."""
        return sum(1 for s in self.seen if s.method == "POST")


def ollama_body(content: str) -> bytes:
    return json.dumps(
        {
            "model": "m",
            "message": {"role": "assistant", "content": content},
            "done": True,
            "prompt_eval_count": 5,
            "eval_count": 2,
        }
    ).encode()


def _body_for(state: ScriptState, step: Step, path: str) -> bytes:
    if step.body is not None:
        return step.body
    if step.status != 200:
        return json.dumps({"error": {"message": "scripted", "code": step.status}}).encode()
    if path.startswith("/api/"):
        return ollama_body(state.content)
    body = completion_json(state.content)
    if state.model_name == "loop":
        return body
    parsed = json.loads(body)
    parsed["model"] = state.model_name
    return json.dumps(parsed).encode()


def _handler(state: ScriptState) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            return

        def do_GET(self) -> None:
            body = json.dumps(state.tags).encode()
            state.seen.append(Seen(self.path, {}, "GET"))
            self._send(200, {}, body)

        def do_POST(self) -> None:
            raw = self.rfile.read(int(self.headers.get("content-length", "0")))
            state.seen.append(Seen(self.path, json.loads(raw or b"{}")))
            with state.lock:
                step = state.steps.pop(0) if state.steps else Step()
            if step.delay_s:
                time.sleep(step.delay_s)
            body = _body_for(state, step, self.path)
            try:
                self._send(step.status, step.headers, body)
            except (BrokenPipeError, ConnectionResetError):
                return

        def _send(self, status: int, headers: dict[str, str], body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            for key, value in headers.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

    return Handler


@contextmanager
def serve_script(
    steps: list[Step] | None = None,
    *,
    content: str = "OK",
    tags: Mapping[str, object] | None = None,
    model_name: str = "loop",
) -> Iterator[tuple[str, ScriptState]]:
    """Run the server; yields ``(origin, state)`` with ``origin = http://127.0.0.1:<port>``."""
    state = ScriptState(
        steps=list(steps or []), content=content, tags=tags or {}, model_name=model_name
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(state))
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", state
    finally:
        server.shutdown()
        server.server_close()
