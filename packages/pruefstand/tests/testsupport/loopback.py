"""Loopback HTTP servers for the hardening tests (real sockets, no model stand-in).

They speak just enough of the OpenAI chat-completions wire format to exercise how the backend and
the cassette hooks treat hostile or sloppy servers (cookies, secrets in headers, slow or huge bodies).
"""

import json
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def completion_json(content: str) -> bytes:
    body = {
        "id": "chatcmpl-loop",
        "object": "chat.completion",
        "model": "loop",
        "choices": [
            {"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}
        ],
        "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
    }
    return json.dumps(body).encode()


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    extra_headers: dict[str, str] = {}
    content = "ok"
    drip_s = 0.0
    huge_bytes = 0

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return

    def do_POST(self) -> None:  # noqa: N802
        self.rfile.read(int(self.headers.get("content-length", "0")))
        try:
            if self.drip_s:
                self._drip()
            elif self.huge_bytes:
                self._huge()
            else:
                self._plain()
        except (BrokenPipeError, ConnectionResetError):
            return

    def _plain(self) -> None:
        body = completion_json(self.content)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for key, value in self.extra_headers.items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _drip(self) -> None:
        body = completion_json("langsam")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        for i in range(len(body)):
            self.wfile.write(body[i : i + 1])
            self.wfile.flush()
            time.sleep(self.drip_s)

    def _huge(self) -> None:
        head, tail = completion_json("@@").split(b"@@")
        total = len(head) + self.huge_bytes + len(tail)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(total))
        self.end_headers()
        self.wfile.write(head)
        chunk = b"a" * (1 << 20)
        sent = 0
        while sent < self.huge_bytes:
            piece = chunk[: min(len(chunk), self.huge_bytes - sent)]
            self.wfile.write(piece)
            sent += len(piece)
        self.wfile.write(tail)


@contextmanager
def serve(
    *,
    headers: dict[str, str] | None = None,
    content: str = "ok",
    drip_s: float = 0.0,
    huge_bytes: int = 0,
) -> Iterator[str]:
    """Run a loopback server; yields its ``http://127.0.0.1:<port>/v1`` base URL."""
    handler = type(
        "Handler",
        (_Handler,),
        {"extra_headers": headers or {}, "content": content, "drip_s": drip_s, "huge_bytes": huge_bytes},
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/v1"
    finally:
        server.shutdown()
        server.server_close()
