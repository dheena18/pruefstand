"""A loopback stand-in for the OpenAI-compatible ``/v1/models`` + ``/v1/chat/completions`` routes.

Plumbing tests only (served-alias checks, request bodies), like ``qa_support.datagen_server``: it
answers what the test scripts, so it never stands in for model behaviour. Real answers come from
the VM model in the ``live`` tests and the recorded fixtures.
"""

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


@dataclass
class StubState:
    """What the stub serves and what it received."""

    served: list[str]
    reply: str = "{}"
    answer_model: str | None = None
    bodies: list[dict[str, Any]] = field(default_factory=list)


@contextmanager
def openai_stub(
    served: list[str], reply: str = "{}", answer_model: str | None = None
) -> Iterator[tuple[str, StubState]]:
    """Serve ``served`` aliases on ``/v1/models``; yield (base URL ``.../v1``, state).

    Answers name the requested model (as llama-server does) unless ``answer_model`` is given.
    """
    state = StubState(served=list(served), reply=reply, answer_model=answer_model)

    class Handler(BaseHTTPRequestHandler):
        def _send(self, payload: dict[str, Any]) -> None:
            data = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            self._send({"object": "list", "data": [{"id": m} for m in state.served]})

        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state.bodies.append(body)
            msg = {"role": "assistant", "content": state.reply}
            model = state.answer_model or body.get("model")
            self._send({"model": model, "choices": [{"message": msg}]})

        def log_message(self, *_: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/v1", state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
