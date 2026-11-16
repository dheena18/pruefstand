"""D1078 accounting: refused connections and a failed thread start leak no slot or peer count."""

import http.client
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import llm_proxy as proxy
import llm_proxy_server
import pytest
import yaml
from llm_proxy_policy import build_policy

ROOT = Path(__file__).resolve().parents[4]
CATALOGUE = yaml.safe_load((ROOT / "infra/gpu/models.yaml").read_text(encoding="utf-8"))["models"]
A, B = "127.0.0.4", "127.0.0.5"


def _server(cap: int, per_peer: int) -> llm_proxy_server.BoundedServer:
    cfg = proxy.ProxyConfig(
        key="unit-test-key", policy=build_policy(CATALOGUE, ["bge-m3"]), upstream="http://127.0.0.1:9",
        client_timeout_s=5, max_connections=cap, request_deadline_s=5,
        trusted_peers=frozenset({"127.0.0.2"}), per_peer_connections=per_peer,
    )  # fmt: skip
    return proxy.serve(cfg, ("0.0.0.0", 0))  # noqa: S104 - test binds all loopback addresses


@pytest.fixture
def server() -> Iterator[llm_proxy_server.BoundedServer]:
    srv = _server(cap=2, per_peer=2)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()


def _health(port: int, source: str) -> bool:
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2, source_address=(source, 0))
        conn.request("GET", "/health")
        ok = conn.getresponse().status == 200
        conn.close()
    except OSError:
        return False
    return ok


def test_refused_connections_do_not_leak_the_peer_count(
    server: llm_proxy_server.BoundedServer,
) -> None:
    port = int(server.server_address[1])
    held = [
        socket.create_connection(("127.0.0.1", port), timeout=5, source_address=(A, 0))
        for _ in range(2)
    ]
    time.sleep(0.2)
    refused = [_health(port, B) for _ in range(5)]  # cap full: B refused 5 times > per_peer 2
    assert not any(refused)
    for sock in held:
        sock.close()
    time.sleep(0.5)
    assert _health(port, B)
    two = [
        socket.create_connection(("127.0.0.1", port), timeout=5, source_address=(B, 0))
        for _ in range(2)
    ]
    try:
        time.sleep(0.2)
        assert not _health(port, B)  # B's own two connections are its per-peer limit, not a leak
    finally:
        for sock in two:
            sock.close()


def test_failed_thread_start_releases_slot_and_peer(monkeypatch: pytest.MonkeyPatch) -> None:
    srv = _server(cap=1, per_peer=1)
    left, right = socket.socketpair()
    try:

        def boom(self: threading.Thread) -> None:
            msg = "can't start new thread"
            raise RuntimeError(msg)

        with monkeypatch.context() as patch:
            patch.setattr(threading.Thread, "start", boom)
            with pytest.raises(RuntimeError):
                srv.process_request(right, (B, 1))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        assert _health(int(srv.server_address[1]), B)  # the one slot and B's one count are free
    finally:
        left.close()
        right.close()  # closing twice is harmless if the server already shut it
        srv.shutdown()
