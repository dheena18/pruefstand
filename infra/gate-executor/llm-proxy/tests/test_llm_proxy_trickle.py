"""Trickling clients (D1075): a total per-request deadline and /health outside the connection cap.

Repro of the #137 re-review: with an idle timeout alone, clients sending one byte per second keep
every slot forever. Small limits are injected (cap 4, timeout 2 s, deadline 3 s).
"""

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
from llm_proxy_policy import build_policy

ROOT = Path(__file__).resolve().parents[4]
CATALOGUE = yaml.safe_load((ROOT / "infra/gpu/models.yaml").read_text(encoding="utf-8"))["models"]


@pytest.fixture
def port() -> Iterator[int]:
    cfg = proxy.ProxyConfig(
        key="unit-test-key", policy=build_policy(CATALOGUE, ["bge-m3"]), upstream="http://127.0.0.1:9",
        client_timeout_s=2, max_connections=4, request_deadline_s=3,
    )  # fmt: skip
    server = proxy.serve(cfg, ("127.0.0.1", 0))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield int(server.server_address[1])
    server.shutdown()


def _trickle(port: int, stop: threading.Event, closed: list[float]) -> None:
    sock = socket.create_connection(("127.0.0.1", port), timeout=10)
    try:
        sock.sendall(b"POST /api/chat HTTP/1.1\r\n")
        while not stop.is_set():
            sock.sendall(b"X")  # one header byte per 0.5 s: the idle timeout never fires
            time.sleep(0.5)
    except OSError:
        closed.append(time.monotonic())
    finally:
        sock.close()


def _health(port: int) -> int:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", "/health")
    resp = conn.getresponse()
    json.loads(resp.read())
    conn.close()
    return resp.status


def test_health_answers_while_tricklers_hold_every_slot_and_they_are_cut(port: int) -> None:
    stop, closed = threading.Event(), list[float]()
    threads = [threading.Thread(target=_trickle, args=(port, stop, closed)) for _ in range(4)]
    for thread in threads:
        thread.start()
    time.sleep(0.5)
    try:
        assert _health(port) == 200  # reserved slot, outside the cap of 4
        for thread in threads:
            thread.join(8)  # the 3 s deadline closes them; a write then fails
        assert len(closed) == 4
    finally:
        stop.set()
    assert _health(port) == 200


def test_reserved_slot_serves_only_health(port: int) -> None:
    held = [socket.create_connection(("127.0.0.1", port), timeout=5) for _ in range(4)]
    try:
        time.sleep(0.3)
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", "/api/tags", headers={"Authorization": "Bearer unit-test-key"})
        assert conn.getresponse().status == 503
        conn.close()
    finally:
        for sock in held:
            sock.close()
