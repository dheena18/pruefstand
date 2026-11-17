"""T8.4: kill switch, rate limit, budget, concurrency and timeout of the public app."""

import asyncio
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


@respx.mock
def test_the_kill_switch_flag_answers_503_before_any_backend_call(tmp_path: Path) -> None:
    llm = mock_backend()
    client = client_for(tmp_path)
    (tmp_path / "disabled").write_text("", encoding="utf-8")
    assert_public_error(client.post("/v1/query", json=query_body()), 503, "demo_disabled")
    assert llm.call_count == 0
    (tmp_path / "disabled").unlink()
    assert client.post("/v1/query", json=query_body()).status_code == 200  # per request, no restart


@respx.mock
def test_the_second_request_is_rate_limited_and_cf_connecting_ip_changes_nothing(
    tmp_path: Path,
) -> None:
    mock_backend()
    client = client_for(tmp_path, demo_rate_per_min=1, trusted_proxy_hops=1)
    ok = client.post(
        "/v1/query", json=query_body(), headers={"X-Forwarded-For": "6.6.6.6, 1.1.1.1"}
    )
    assert ok.status_code == 200
    # a forged first hop and a changing CF-Connecting-IP do not give a new key
    again = client.post(
        "/v1/query",
        json=query_body(),
        headers={"X-Forwarded-For": "7.7.7.7, 1.1.1.1", "CF-Connecting-IP": "9.9.9.9"},
    )
    assert_public_error(again, 429, "rate_limited")
    assert again.json()["retry_after_s"] > 0
    assert again.headers["retry-after"] == str(again.json()["retry_after_s"])
    other = client.post("/v1/query", json=query_body(), headers={"X-Forwarded-For": "1.1.1.2"})
    assert other.status_code == 200  # another visitor behind the proxy


@respx.mock
def test_zero_trusted_hops_key_on_the_peer_and_ignore_forwarded_for(tmp_path: Path) -> None:
    mock_backend()
    client = client_for(tmp_path, demo_rate_per_min=1, trusted_proxy_hops=0)
    first = client.post("/v1/query", json=query_body(), headers={"X-Forwarded-For": "1.1.1.1"})
    assert first.status_code == 200
    again = client.post("/v1/query", json=query_body(), headers={"X-Forwarded-For": "2.2.2.2"})
    assert_public_error(again, 429, "rate_limited")


@respx.mock
def test_the_daily_token_budget_is_503_budget_exhausted(tmp_path: Path) -> None:
    mock_backend()
    client = client_for(tmp_path, demo_daily_tokens=300, demo_rate_per_min=100)
    assert client.post("/v1/query", json=query_body()).status_code == 200  # reserves 256, settles 0
    refused = client.post("/v1/query", json=query_body())
    assert refused.status_code == 200  # the settle refunded the reserve
    tiny = client_for(tmp_path, demo_daily_tokens=100)
    assert_public_error(tiny.post("/v1/query", json=query_body()), 503, "budget_exhausted")


@respx.mock
def test_a_generation_over_the_server_timeout_is_504_timeout(tmp_path: Path) -> None:
    async def slow(_: httpx.Request) -> httpx.Response:
        await asyncio.sleep(1.0)
        return httpx.Response(200, json=REPLY)

    mock_backend(slow)
    resp = client_for(tmp_path, demo_timeout_s=0.05).post("/v1/query", json=query_body())
    assert_public_error(resp, 504, "timeout")


@respx.mock
def test_the_kill_switch_comes_before_the_rate_limit(tmp_path: Path) -> None:
    mock_backend()
    client = client_for(tmp_path, demo_rate_per_min=1)
    (tmp_path / "disabled").write_text("", encoding="utf-8")
    assert_public_error(client.post("/v1/query", json=query_body()), 503, "demo_disabled")
    (tmp_path / "disabled").unlink()
    assert client.post("/v1/query", json=query_body()).status_code == 200  # no token was spent


@respx.mock
def test_a_budget_refusal_releases_the_concurrency_slot(tmp_path: Path) -> None:
    mock_backend()
    client = client_for(
        tmp_path, demo_daily_tokens=10, demo_max_concurrency=1, demo_rate_per_min=100
    )
    for _ in range(3):  # a leaked slot would turn the second answer into `busy`
        assert_public_error(client.post("/v1/query", json=query_body()), 503, "budget_exhausted")


@respx.mock
def test_the_concurrency_slot_is_taken_before_the_budget(tmp_path: Path) -> None:
    started, release = threading.Event(), threading.Event()

    async def held(_: httpx.Request) -> httpx.Response:
        started.set()
        await asyncio.to_thread(release.wait, 10)
        return httpx.Response(200, json=REPLY)

    mock_backend(held)
    client = client_for(
        tmp_path, demo_daily_tokens=300, demo_max_concurrency=1, demo_rate_per_min=100
    )
    worker = threading.Thread(target=lambda: client.post("/v1/query", json=query_body()))
    worker.start()
    assert started.wait(5)
    # the budget is also nearly used (256 reserved of 300), but the answer must be `busy`
    assert_public_error(client.post("/v1/query", json=query_body()), 429, "busy")
    release.set()
    worker.join(5)


@respx.mock
def test_a_timed_out_generation_keeps_its_worst_case_reserved(tmp_path: Path) -> None:
    async def slow(_: httpx.Request) -> httpx.Response:
        await asyncio.sleep(1.0)
        return httpx.Response(200, json=REPLY)

    mock_backend(slow)
    client = client_for(tmp_path, demo_timeout_s=0.05, demo_daily_tokens=300, demo_rate_per_min=100)
    assert_public_error(client.post("/v1/query", json=query_body()), 504, "timeout")
    # 256 tokens stay charged (the generator may have run to its limit): 512 > 300
    assert_public_error(client.post("/v1/query", json=query_body()), 503, "budget_exhausted")


@respx.mock
def test_retrieve_has_the_kill_switch_the_rate_limit_and_public_errors(tmp_path: Path) -> None:
    mock_backend()
    client = client_for(tmp_path, demo_rate_per_min=2)
    ok = client.post("/v1/retrieve", json=query_body(request_id="r1"))
    assert ok.status_code == 200
    unknown = client.post("/v1/retrieve", json=query_body(tenant_id="evil_corp", request_id="r2"))
    assert_public_error(unknown, 422, "invalid_request")
    assert_public_error(
        client.post("/v1/retrieve", json=query_body(request_id="r3")), 429, "rate_limited"
    )
    (tmp_path / "disabled").write_text("", encoding="utf-8")
    assert_public_error(
        client.post("/v1/retrieve", json=query_body(request_id="r4")), 503, "demo_disabled"
    )


@respx.mock
def test_every_forwarded_for_header_line_counts_not_only_the_last(tmp_path: Path) -> None:
    mock_backend()
    client = client_for(tmp_path, demo_rate_per_min=1, trusted_proxy_hops=2)

    def post(*lines: str) -> object:
        headers = [("X-Forwarded-For", line) for line in lines]
        return client.post("/v1/query", json=query_body(), headers=headers)

    # both header lines are joined: the key is the 2nd hop from the right = 1.1.1.1
    assert post("5.5.5.5, 1.1.1.1", "2.2.2.2").status_code == 200  # type: ignore[attr-defined]
    again = post("6.6.6.6, 1.1.1.1", "3.3.3.3")
    assert_public_error(again, 429, "rate_limited")  # the same visitor 1.1.1.1
    # another visitor behind the proxy has another key; reading only the last line would give
    # both requests the same (peer) key and refuse this one
    other = post("5.5.5.5, 9.9.9.9", "2.2.2.2")
    assert other.status_code == 200  # type: ignore[attr-defined]
