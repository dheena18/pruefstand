"""Issue #164 (D1078): reserve slots only for trusted peers, and a per-peer connection limit.

Reproduction: 40 threads loop "connect, send GET /hea, one byte every 0.3 s until closed" from
127.0.0.1 (untrusted here), while /health is polled from 127.0.0.2 (the trusted peer here).
Cap 4, request deadline 5 s, reserve deadline 2 s. Linux routes all of 127.0.0.0/8 to loopback.
"""

import http.client
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
TRUSTED = "127.0.0.2"


@pytest.fixture
def port() -> Iterator[int]:
    cfg = proxy.ProxyConfig(
        key="unit-test-key", policy=build_policy(CATALOGUE, ["bge-m3"]), upstream="http://127.0.0.1:9",
        client_timeout_s=5, max_connections=4, request_deadline_s=5, reserve_deadline_s=2,
        trusted_peers=frozenset({TRUSTED}), per_peer_connections=4,
    )  # fmt: skip
    server = proxy.serve(cfg, ("0.0.0.0", 0))  # noqa: S104 - test binds all loopback addresses
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield int(server.server_address[1])
    server.shutdown()


def _loop_trickler(port: int, stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=3) as sock:
                sock.sendall(b"GET /hea")
                while not stop.wait(0.3):
                    sock.sendall(b"a")
        except OSError:
            continue


def _health(port: int, source: str) -> bool:
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2, source_address=(source, 0))
        conn.request("GET", "/health")
        ok = conn.getresponse().status == 200
        conn.close()
    except OSError:
        return False
    return ok


def test_trusted_health_survives_40_reconnecting_tricklers(port: int) -> None:
    stop = threading.Event()
    threads = [threading.Thread(target=_loop_trickler, args=(port, stop)) for _ in range(40)]
    for thread in threads:
        thread.start()
    try:
        time.sleep(0.5)
        results = [_health(port, TRUSTED) for _ in range(15)]
    finally:
        stop.set()
        for thread in threads:
            thread.join(5)
    assert sum(results) >= 14, results


def test_untrusted_peer_never_gets_a_reserve_slot(port: int) -> None:
    held = [socket.create_connection(("127.0.0.1", port), timeout=5) for _ in range(4)]
    try:
        time.sleep(0.2)
        assert not _health(port, "127.0.0.1")  # cap full, no reserve for this peer
        assert _health(port, TRUSTED)
    finally:
        for sock in held:
            sock.close()


def test_per_peer_limit_closes_extra_connections() -> None:
    cfg = proxy.ProxyConfig(
        key="unit-test-key", policy=build_policy(CATALOGUE, ["bge-m3"]), upstream="http://127.0.0.1:9",
        client_timeout_s=5, max_connections=8, request_deadline_s=5,
        trusted_peers=frozenset({TRUSTED}), per_peer_connections=2,
    )  # fmt: skip
    server = proxy.serve(cfg, ("0.0.0.0", 0))  # noqa: S104 - see above
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = int(server.server_address[1])
    held = [socket.create_connection(("127.0.0.1", port), timeout=5) for _ in range(2)]
    try:
        time.sleep(0.2)
        assert not _health(port, "127.0.0.1")  # third connection of the same peer
        assert _health(port, "127.0.0.3")  # another peer still gets a normal slot
    finally:
        for sock in held:
            sock.close()
        server.shutdown()


def test_defaults_trust_only_loopback() -> None:
    cfg = proxy.ProxyConfig(key="k", policy=build_policy(CATALOGUE, ["bge-m3"]))
    assert cfg.trusted_peers == frozenset({"127.0.0.1", "::1"})
    assert cfg.per_peer_connections == 16
