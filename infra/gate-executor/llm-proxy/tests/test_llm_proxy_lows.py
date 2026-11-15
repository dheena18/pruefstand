"""#137 low findings (D1077): nesting, reserve starvation, short bodies, bad request lines, seed."""

import http.client
import json
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import llm_proxy as proxy
import pytest
import yaml
from llm_proxy_policy import Reject, build_policy, decide

ROOT = Path(__file__).resolve().parents[4]
CATALOGUE = yaml.safe_load((ROOT / "infra/gpu/models.yaml").read_text(encoding="utf-8"))["models"]
GEN = "qwen3.8:27b-q8_0"
KEY = "unit-test-key"
POLICY = build_policy(CATALOGUE, [GEN])


def _post(raw: bytes) -> object:
    return decide("POST", "/api/chat", auth=f"Bearer {KEY}", body=raw, key=KEY, policy=POLICY)


def test_deep_nesting_is_a_403_not_a_dropped_connection() -> None:
    depth = 100_000
    raw = f'{{"model": "{GEN}", "messages": '.encode() + b"[" * depth + b"]" * depth + b"}"
    verdict = _post(raw)
    assert isinstance(verdict, Reject)
    assert verdict.status == 403


@pytest.mark.parametrize("seed", [-1, 2**31, 2**63])
def test_seed_outside_int32_is_rejected(seed: int) -> None:
    raw = json.dumps({"model": GEN, "messages": [], "options": {"seed": seed}}).encode()
    assert _post(raw) == Reject(403, "option out of bounds: seed")


@pytest.mark.parametrize("seed", [0, 7, 2**31 - 1])
def test_seed_inside_int32_passes(seed: int) -> None:
    raw = json.dumps({"model": GEN, "messages": [], "options": {"seed": seed}}).encode()
    assert not isinstance(_post(raw), Reject)


@pytest.fixture
def port() -> Iterator[int]:
    cfg = proxy.ProxyConfig(
        key=KEY, policy=POLICY, upstream="http://127.0.0.1:9", client_timeout_s=10,
        max_connections=4, request_deadline_s=30, reserve_deadline_s=1,
    )  # fmt: skip
    server = proxy.serve(cfg, ("127.0.0.1", 0))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield int(server.server_address[1])
    server.shutdown()


def _health(port: int) -> int | None:
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        conn.request("GET", "/health")
        status = conn.getresponse().status
        conn.close()
    except OSError:
        return None
    return status


def _trickle(port: int, stop: threading.Event) -> None:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=10) as sock:
            sock.sendall(b"GET /hea")
            while not stop.wait(0.3):
                sock.sendall(b"a")
    except OSError:
        return


def test_tricklers_on_reserve_slots_cannot_starve_health(port: int) -> None:
    stop = threading.Event()
    threads = [threading.Thread(target=_trickle, args=(port, stop)) for _ in range(6)]
    for thread in threads:
        thread.start()
    try:
        time.sleep(0.3)
        deadline = time.monotonic() + 8  # reserve deadline is 1 s; the normal one 30 s
        status = None
        while status != 200 and time.monotonic() < deadline:
            status = _health(port)
            if status != 200:
                time.sleep(0.2)
        assert status == 200
    finally:
        stop.set()
        for thread in threads:
            thread.join(5)


def _raw(port: int, data: bytes, *, half_close: bool = False) -> bytes:
    with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
        sock.sendall(data)
        if half_close:
            sock.shutdown(socket.SHUT_WR)
        chunks = []
        while chunk := sock.recv(4096):
            chunks.append(chunk)
    return b"".join(chunks)


def test_short_body_is_rejected(port: int) -> None:
    body = json.dumps({"model": GEN, "messages": []}).encode()
    head = (
        f"POST /api/chat HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer {KEY}\r\n"
        f"Content-Length: {len(body) + 50}\r\n\r\n"
    ).encode()
    answer = _raw(port, head + body, half_close=True)
    assert answer.startswith(b"HTTP/1.1 403")
    assert b"body shorter than Content-Length" in answer


@pytest.mark.parametrize(
    ("line", "code"),
    [
        (b"GARBAGE\r\n\r\n", b"400"),
        (b"GET /" + b"a" * 70_000 + b" HTTP/1.1\r\n\r\n", b"414"),
        (b"GET / HTTP/2.0\r\n\r\n", b"505"),
    ],
)
def test_malformed_request_lines_get_their_error(port: int, line: bytes, code: bytes) -> None:
    answer = _raw(port, line)
    # before a valid request line the stdlib answers HTTP/0.9-style (no status line), body only
    assert b"Error code: " + code in answer
