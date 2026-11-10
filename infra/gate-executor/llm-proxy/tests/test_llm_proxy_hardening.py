"""Server hardening from the #137 review (D1071–D1073): local tags, no redirects, no env proxy,
client socket timeout and a connection cap. Local upstream on 127.0.0.1, injected small limits."""

import http.client
import json
import socket
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import llm_proxy as proxy
import pytest
import yaml
from llm_proxy_policy import build_policy

ROOT = Path(__file__).resolve().parents[4]
CATALOGUE = yaml.safe_load((ROOT / "infra/gpu/models.yaml").read_text(encoding="utf-8"))["models"]
GEN, EMB = "qwen3.8:27b-q8_0", "bge-m3"
KEY = "unit-test-key"
CHAT = {"model": GEN, "messages": [{"role": "user", "content": "Frist?"}]}


class Upstream(BaseHTTPRequestHandler):
    seen: list[str] = []  # noqa: RUF012 - per-test reset below
    redirect = False

    def do_GET(self) -> None:
        self._answer()

    def do_POST(self) -> None:
        self.rfile.read(int(self.headers.get("Content-Length", "0") or 0))
        self._answer()

    def _answer(self) -> None:
        type(self).seen.append(self.path)
        if type(self).redirect:
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:9/api/pull")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body = b'{"models": [{"name": "gemma3:12b"}]}'
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - stdlib name
        return


def _start(server: ThreadingHTTPServer) -> None:
    threading.Thread(target=server.serve_forever, daemon=True).start()


@pytest.fixture
def ports() -> Iterator[tuple[int, int]]:
    Upstream.seen, Upstream.redirect = [], False
    up = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    _start(up)
    cfg = proxy.ProxyConfig(
        key=KEY, policy=build_policy(CATALOGUE, [GEN, EMB]),
        upstream=f"http://127.0.0.1:{up.server_address[1]}", timeout_s=5,
        client_timeout_s=0.5, max_connections=2,
    )  # fmt: skip
    server = proxy.serve(cfg, ("127.0.0.1", 0))
    _start(server)
    yield int(server.server_address[1]), int(up.server_address[1])
    server.shutdown()
    up.shutdown()


def _call(port: int, method: str, path: str, body: object = None) -> tuple[int, dict[str, object]]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    data = None if body is None else json.dumps(body).encode()
    conn.request(method, path, body=data, headers={"Authorization": f"Bearer {KEY}"})
    resp = conn.getresponse()
    out = json.loads(resp.read())
    conn.close()
    return resp.status, out


def test_tags_come_from_the_policy_never_from_upstream(ports: tuple[int, int]) -> None:
    status, body = _call(ports[0], "GET", "/api/tags")
    assert status == 200
    assert "gemma3:12b" not in json.dumps(body)
    assert Upstream.seen == []


def test_upstream_redirect_is_refused_as_502(ports: tuple[int, int]) -> None:
    Upstream.redirect = True
    assert _call(ports[0], "POST", "/api/chat", CHAT)[0] == 502
    assert Upstream.seen == ["/api/chat"]
    assert _call(ports[0], "GET", "/health")[1]["upstream_errors"] == 1


def test_environment_proxies_are_ignored(
    ports: tuple[int, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("HTTP_PROXY", "http_proxy", "ALL_PROXY"):
        monkeypatch.setenv(name, "http://127.0.0.1:9")
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    assert _call(ports[0], "POST", "/api/chat", CHAT)[0] == 200
    assert Upstream.seen == ["/api/chat"]


def _idle(port: int) -> socket.socket:
    sock = socket.create_connection(("127.0.0.1", port), timeout=5)
    sock.sendall(b"POST /api/chat HTTP/1.1\r\nHost: x\r\n")
    return sock


def test_a_slow_client_is_cut_off_by_the_socket_timeout(ports: tuple[int, int]) -> None:
    sock = _idle(ports[0])
    try:
        assert sock.recv(1024) == b""  # closed by the server after client_timeout_s, not 5 s
    finally:
        sock.close()


def test_connections_beyond_cap_and_reserve_are_closed_at_once(ports: tuple[int, int]) -> None:
    held = [_idle(ports[0]) for _ in range(2 + 2)]  # cap 2 + the 2 reserved /health slots
    extra = socket.create_connection(("127.0.0.1", ports[0]), timeout=5)
    try:
        extra.sendall(b"GET /health HTTP/1.1\r\nHost: x\r\n\r\n")
        assert extra.recv(1024) == b""
    finally:
        extra.close()
        for sock in held:
            sock.close()
