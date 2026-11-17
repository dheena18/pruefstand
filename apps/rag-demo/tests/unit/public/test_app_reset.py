"""T8.4: the test-only reset route (N5.4, P5.4, UI13-15)."""

import asyncio
import json
import threading
from pathlib import Path

import httpx
import respx
from pub_support import (
    REPLY,
    assert_public_error,
    client_for,
    mock_backend,
    query_body,
)
from rd_support import CONFIGS


@respx.mock
def test_the_reset_route_is_absent_without_the_env(tmp_path: Path) -> None:
    mock_backend()
    client = client_for(tmp_path, peer="127.0.0.1")
    assert client.post("/v1/_test/reset").status_code == 404
    assert "/v1/_test/reset" not in json.dumps(client.get("/openapi.json").json())


@respx.mock
def test_reset_from_loopback_admits_a_limited_key_again(tmp_path: Path) -> None:
    mock_backend()
    client = client_for(tmp_path, peer="127.0.0.1", demo_test_reset="1", demo_rate_per_min=1)
    assert client.post("/v1/query", json=query_body()).status_code == 200
    assert_public_error(client.post("/v1/query", json=query_body()), 429, "rate_limited")
    assert client.post("/v1/_test/reset").status_code == 204
    assert client.post("/v1/query", json=query_body()).status_code == 200
    assert "/v1/_test/reset" not in json.dumps(client.get("/openapi.json").json())


@respx.mock
def test_reset_from_a_non_loopback_peer_is_404_even_with_a_forged_header(tmp_path: Path) -> None:
    mock_backend()
    client = client_for(tmp_path, peer="172.18.0.1", demo_test_reset="1")
    resp = client.post("/v1/_test/reset", headers={"X-Forwarded-For": "127.0.0.1"})
    assert resp.status_code == 404
    v6 = client_for(tmp_path, peer="::1", demo_test_reset="1")
    assert v6.post("/v1/_test/reset").status_code == 204


@respx.mock
def test_reset_during_a_running_generation_is_409_and_changes_nothing(tmp_path: Path) -> None:
    started = threading.Event()
    release = threading.Event()

    async def held(_: httpx.Request) -> httpx.Response:
        started.set()
        await asyncio.to_thread(release.wait, 10)
        return httpx.Response(200, json=REPLY)

    mock_backend(held)
    client = client_for(tmp_path, peer="127.0.0.1", demo_test_reset="1", demo_rate_per_min=1)
    result: dict[str, int] = {}
    worker = threading.Thread(
        target=lambda: result.update(status=client.post("/v1/query", json=query_body()).status_code)
    )
    worker.start()
    assert started.wait(5)
    busy = client.post("/v1/_test/reset")
    assert busy.status_code == 409
    assert busy.json()["code"] == "busy"
    release.set()
    worker.join(5)
    assert result["status"] == 200
    assert_public_error(
        client.post("/v1/query", json=query_body()), 429, "rate_limited"
    )  # unchanged
    assert client.post("/v1/_test/reset").status_code == 204


def test_the_public_profile_never_sets_the_test_reset() -> None:
    text = (CONFIGS / "rag.public.yaml").read_text(encoding="utf-8")
    assert "DEMO_TEST_RESET" not in text.upper()
    assert "test_reset" not in text
