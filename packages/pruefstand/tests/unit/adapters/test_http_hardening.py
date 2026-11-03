"""The target is untrusted: hostile, huge, slow and redirecting responses (T1.3 hardening)."""

import asyncio
import time
from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
import respx
from contract.adapter_contract import load_example

from pruefstand.adapters.http import MAX_RESPONSE_BYTES, HttpTargetAdapter
from pruefstand.core.config import HttpTargetConfig
from pruefstand.core.errors import ConfigError, TargetError
from pruefstand.core.ids import TenantId
from pruefstand.core.models.target import TargetRequest

BASE = "http://target.test"
REQ = TargetRequest(tenant_id=TenantId("public"), question="Frage", top_k=None, request_id="c-1")
CHUNK = '{"chunk_id": "c", "doc_id": "d", "text": "t", "score": %s, "rank": 1}'


@pytest.fixture
def router() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        yield mock


@pytest.fixture
async def adapter() -> AsyncIterator[HttpTargetAdapter]:
    instance = HttpTargetAdapter(HttpTargetConfig(type="http", url=BASE, timeout_s=2))
    yield instance
    await instance.aclose()


async def test_oversized_body_is_rejected_permanently(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    router.post("/v1/query").respond(200, content=b"{" + b" " * (MAX_RESPONSE_BYTES + 10))
    with pytest.raises(TargetError, match="too large") as excinfo:
        await adapter.query(REQ)
    assert excinfo.value.transient is False


async def test_declared_content_length_over_limit_is_rejected(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    router.post("/v1/query").respond(
        200, content=b"{}", headers={"content-length": str(MAX_RESPONSE_BYTES + 1)}
    )
    with pytest.raises(TargetError, match="too large"):
        await adapter.query(REQ)


@pytest.mark.parametrize(
    "location", ["/elsewhere", "http://other.test/v1/query", "file:///etc/passwd"]
)
async def test_redirects_are_not_followed(
    router: respx.MockRouter, adapter: HttpTargetAdapter, location: str
) -> None:
    router.post("/v1/query").respond(302, headers={"location": location})
    follow = router.route().respond(200, json=load_example("query_ok.json"))
    with pytest.raises(TargetError, match="redirect") as excinfo:
        await adapter.query(REQ)
    assert excinfo.value.transient is False
    assert follow.call_count == 0
    assert "passwd" not in str(excinfo.value)


async def test_redirect_on_info_is_an_error_not_none(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    router.get("/v1/info").respond(301, headers={"location": "/x"})
    with pytest.raises(TargetError, match="redirect"):
        await adapter.info()


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://x.test", "http://user:pw@x.test"])
def test_non_http_or_credential_urls_are_refused(url: str) -> None:
    cfg = HttpTargetConfig.model_construct(type="http", url=url, auth_env=None, timeout_s=5.0)
    with pytest.raises(ConfigError):
        HttpTargetAdapter(cfg)


class _Drip(httpx.AsyncByteStream):
    async def __aiter__(self) -> AsyncIterator[bytes]:
        for _ in range(100):  # 10 s in all; the total timeout is 0.5 s
            await asyncio.sleep(0.1)
            yield b" "


async def test_total_timeout_bounds_a_slow_drip(router: respx.MockRouter) -> None:
    router.post("/v1/query").mock(return_value=httpx.Response(200, stream=_Drip()))
    adapter = HttpTargetAdapter(HttpTargetConfig(type="http", url=BASE, timeout_s=0.5))
    started = time.monotonic()
    with pytest.raises(TargetError, match="timed out") as excinfo:
        await adapter.query(REQ)
    await adapter.aclose()
    assert excinfo.value.transient is True
    assert time.monotonic() - started < 8.0  # wall time is the point; 16x the timeout, < the drip


@pytest.mark.parametrize(
    "body",
    [
        ('{"answer": "a", "chunks": [' + CHUNK % "NaN" + "]}").encode(),
        ('{"answer": "a", "chunks": [' + CHUNK % "Infinity" + "]}").encode(),
        ('{"answer": "a", "chunks": [' + CHUNK % "1e999" + "]}").encode(),
        b"[" * 100_000,
        b'{"answer": "a\\ud800"}',
        b"\xff\xfe\x00",
        b"null",
        b'"just a string"',
    ],
)
async def test_hostile_bodies_become_permanent_target_errors(
    router: respx.MockRouter, adapter: HttpTargetAdapter, body: bytes
) -> None:
    router.post("/v1/query").respond(200, content=body)
    with pytest.raises(TargetError) as excinfo:
        await adapter.query(REQ)
    assert excinfo.value.transient is False
    assert len(str(excinfo.value)) < 600


async def test_error_text_redacts_an_echoed_token(
    router: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TOK", "tok-abcdef-123456")
    router.post("/v1/query").respond(401, text="bad bearer tok-abcdef-123456 \x1b[31m\x00 end")
    adapter = HttpTargetAdapter(HttpTargetConfig(type="http", url=BASE, auth_env="TOK"))
    with pytest.raises(TargetError) as excinfo:
        await adapter.query(REQ)
    await adapter.aclose()
    text = str(excinfo.value)
    assert "tok-abcdef-123456" not in text
    assert "\x1b" not in text
    assert "\x00" not in text


async def test_auth_env_is_read_at_call_time(
    router: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    route = router.post("/v1/query").respond(200, json=load_example("query_ok.json"))
    adapter = HttpTargetAdapter(HttpTargetConfig(type="http", url=BASE, auth_env="TOK2"))
    monkeypatch.setenv("TOK2", "first-token-value")
    await adapter.query(REQ)
    monkeypatch.setenv("TOK2", "second-token-value")
    await adapter.query(REQ)
    await adapter.aclose()
    assert route.calls[0].request.headers["authorization"] == "Bearer first-token-value"
    assert route.calls[1].request.headers["authorization"] == "Bearer second-token-value"


async def test_missing_auth_env_var_is_a_permanent_error_naming_the_variable(
    router: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TOK3", raising=False)
    route = router.post("/v1/query").respond(200, json=load_example("query_ok.json"))
    adapter = HttpTargetAdapter(HttpTargetConfig(type="http", url=BASE, auth_env="TOK3"))
    with pytest.raises(TargetError, match="TOK3") as excinfo:
        await adapter.query(REQ)
    await adapter.aclose()
    assert excinfo.value.transient is False
    assert route.call_count == 0


async def test_one_attempt_per_call_no_retries(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    route = router.post("/v1/query").respond(503)
    with pytest.raises(TargetError):
        await adapter.query(REQ)
    assert route.call_count == 1


async def test_invalid_json_excerpt_redacts_an_echoed_token(
    router: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TOK4", "tok-echo-987654321")
    router.post("/v1/query").respond(200, text="<html>your key tok-echo-987654321</html>")
    adapter = HttpTargetAdapter(HttpTargetConfig(type="http", url=BASE, auth_env="TOK4"))
    with pytest.raises(TargetError) as excinfo:
        await adapter.query(REQ)
    await adapter.aclose()
    assert "tok-echo-987654321" not in str(excinfo.value)
    assert "<html>" in str(excinfo.value)
