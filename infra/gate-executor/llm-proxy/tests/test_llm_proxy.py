"""llm-proxy over HTTP: forwarding, counters, logging, defaults (interfaces 1.5; D206, D242, N6.4).

The upstream is a local stdlib server on 127.0.0.1 that records what reaches it (the proxy's
plumbing is tested, not a model; the live path is T6.2a's [GPU] Done-when item).
"""

import http.client
import json
import logging
import socket
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import llm_proxy as proxy
import pytest
import yaml
from llm_proxy_policy import build_policy

ROOT = Path(__file__).resolve().parents[4]
CATALOGUE = yaml.safe_load((ROOT / "infra/gpu/models.yaml").read_text(encoding="utf-8"))["models"]
GEN, EMB, JUDGE = "qwen3.8:27b-q8_0", "bge-m3", "gemma3:12b"
KEY = "unit-test-key"


@dataclass
class Upstream:
    seen: list[tuple[str, str, bytes]] = field(default_factory=list)
    reply: bytes = b'{"message": {"content": "ok"}, "load_duration": 200000000}'
    status: int = 200


def _upstream_server(state: Upstream) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def _answer(self) -> None:
            body = self.rfile.read(int(self.headers.get("Content-Length", "0") or 0))
            state.seen.append((self.command, self.path, body))
            self.send_response(state.status)
            self.send_header("Content-Length", str(len(state.reply)))
            self.end_headers()
            self.wfile.write(state.reply)

        def do_GET(self) -> None:
            self._answer()

        def do_POST(self) -> None:
            self._answer()

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - stdlib name
            return

    return ThreadingHTTPServer(("127.0.0.1", 0), Handler)


def _start(server: ThreadingHTTPServer) -> None:
    threading.Thread(target=server.serve_forever, daemon=True).start()


@dataclass
class Rig:
    upstream: Upstream
    port: int

    def call(
        self, method: str, path: str, body: Any = None, *, auth: bool = True
    ) -> tuple[int, Any]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {"Authorization": f"Bearer {KEY}"} if auth else {}
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode()
        conn.request(method, path, body=data, headers=headers)
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        return resp.status, json.loads(raw)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def rig() -> Iterator[Rig]:
    state = Upstream()
    up = _upstream_server(state)
    _start(up)
    cfg = proxy.ProxyConfig(
        key=KEY,
        policy=build_policy(CATALOGUE, [GEN, EMB]),
        upstream=f"http://127.0.0.1:{up.server_address[1]}",
        max_body=64 * 1024,
        timeout_s=5,
    )
    server = proxy.serve(cfg, ("127.0.0.1", 0))
    _start(server)
    yield Rig(state, int(server.server_address[1]))
    server.shutdown()
    up.shutdown()


def _chat(model: str = GEN, **extra: Any) -> dict[str, Any]:
    return {"model": model, "messages": [{"role": "user", "content": "Kündigungsfrist?"}], **extra}


def test_allowed_calls_are_forwarded_and_answers_pass_unchanged(rig: Rig) -> None:
    status, body = rig.call("POST", "/api/chat", _chat(keep_alive=0))
    assert (status, body) == (200, json.loads(rig.upstream.reply))
    assert rig.call("POST", "/api/embed", {"model": EMB, "input": ["Miete"]})[0] == 200
    assert rig.call("GET", "/api/tags")[0] == 200
    assert [(m, p) for m, p, _ in rig.upstream.seen] == [
        ("POST", "/api/chat"),
        ("POST", "/api/embed"),
        ("GET", "/api/tags"),
    ]
    assert "keep_alive" not in json.loads(rig.upstream.seen[0][2])
    assert rig.call("GET", "/health")[1] == {
        "model_reloads": 0,
        "upstream_errors": 0,
        "requests": 3,
    }


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("POST", "/v1/chat/completions", _chat()),
        ("POST", "/api/pull", {"model": GEN}),
        ("POST", "/api/generate", _chat()),
        ("GET", "/api/ps", None),
        ("POST", "/api/chat", _chat(model=JUDGE)),
        ("POST", "/api/chat", _chat(options={"temperature": 1.5})),
        ("DELETE", "/api/delete", {"model": GEN}),
    ],
)
def test_rejections_forward_nothing_and_count_nothing(
    rig: Rig, method: str, path: str, body: Any
) -> None:
    status, answer = rig.call(method, path, body)
    assert status == 403
    assert set(answer) == {"error"}
    assert rig.upstream.seen == []
    assert rig.call("GET", "/health")[1] == {
        "model_reloads": 0,
        "upstream_errors": 0,
        "requests": 0,
    }


def test_missing_key_is_rejected(rig: Rig) -> None:
    assert rig.call("POST", "/api/chat", _chat(), auth=False)[0] == 403
    assert rig.upstream.seen == []


@pytest.mark.parametrize("length", ["100000", "zehn", "-1"])
def test_oversized_or_unsized_body_is_rejected_unread(rig: Rig, length: str) -> None:
    conn = http.client.HTTPConnection("127.0.0.1", rig.port, timeout=5)
    conn.putrequest("POST", "/api/chat")
    conn.putheader("Authorization", f"Bearer {KEY}")
    conn.putheader("Content-Length", length)
    conn.endheaders()
    resp = conn.getresponse()
    answer = json.loads(resp.read())
    conn.close()
    assert resp.status == 403
    assert "too large" in answer["error"]
    assert rig.upstream.seen == []


def test_reload_counter_follows_load_duration(rig: Rig) -> None:
    rig.upstream.reply = b'{"load_duration": 2500000000}'
    rig.call("POST", "/api/chat", _chat())
    rig.upstream.reply = b'{"load_duration": 200000000}'
    rig.call("POST", "/api/chat", _chat())
    assert rig.call("GET", "/health")[1]["model_reloads"] == 1


def test_upstream_5xx_counts_as_upstream_error(rig: Rig) -> None:
    rig.upstream.status, rig.upstream.reply = 500, b'{"error": "boom"}'
    assert rig.call("POST", "/api/chat", _chat())[0] == 500
    assert rig.call("GET", "/health")[1] == {
        "model_reloads": 0,
        "upstream_errors": 1,
        "requests": 1,
    }


def test_upstream_refused_is_502_and_counted() -> None:
    cfg = proxy.ProxyConfig(
        key=KEY,
        policy=build_policy(CATALOGUE, [GEN]),
        upstream=f"http://127.0.0.1:{_free_port()}",
        timeout_s=2,
    )
    server = proxy.serve(cfg, ("127.0.0.1", 0))
    _start(server)
    try:
        rig = Rig(Upstream(), int(server.server_address[1]))
        assert rig.call("POST", "/api/chat", _chat())[0] == 502
        assert rig.call("POST", "/api/chat", _chat(model=JUDGE))[0] == 403
        assert rig.call("GET", "/health")[1] == {
            "model_reloads": 0,
            "upstream_errors": 1,
            "requests": 1,
        }
    finally:
        server.shutdown()


def test_log_holds_no_body_and_no_key(rig: Rig, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="llm_proxy")
    rig.call("POST", "/api/chat", _chat())
    rig.call("POST", "/api/chat", _chat(), auth=False)
    text = caplog.text
    assert "Kündigungsfrist" not in text
    assert KEY not in text
    assert "/api/chat" in text


def test_defaults_listen_and_upstream() -> None:
    assert proxy.DEFAULT_LISTEN == ("0.0.0.0", 11500)  # noqa: S104 - asserts the container default
    assert proxy.DEFAULT_UPSTREAM == "http://172.17.0.1:11434"
    policy = json.dumps({GEN: next(e for e in CATALOGUE if e["tag"] == GEN)})
    cfg = proxy.config_from_env({"PRUEFSTAND_CANDIDATE_API_KEY": KEY, "LLM_PROXY_POLICY": policy})
    assert cfg.upstream == "http://172.17.0.1:11434"
    assert set(cfg.policy) == {GEN}


@pytest.mark.parametrize(
    "env",
    [
        {"LLM_PROXY_POLICY": "{}"},
        {"PRUEFSTAND_CANDIDATE_API_KEY": KEY, "LLM_PROXY_POLICY": "{}"},
        {
            "PRUEFSTAND_CANDIDATE_API_KEY": KEY,
            "LLM_PROXY_POLICY": json.dumps({JUDGE: {"role": "judge"}}),
        },
    ],
)
def test_incomplete_env_refuses_to_start(env: dict[str, str]) -> None:
    with pytest.raises(ValueError, match=r"\S"):
        proxy.config_from_env(env)


@pytest.mark.parametrize(
    "url",
    [
        "https://172.17.0.1:11434",
        "http://",
        "http://h:1/api",
        "file:///etc/passwd",
        "http://h:1/?q=1",
    ],
)
def test_upstream_must_be_plain_http_host_port(url: str) -> None:
    with pytest.raises(ValueError, match="LLM_PROXY_UPSTREAM"):
        proxy.check_upstream(url)
