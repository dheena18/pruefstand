"""Review round 1: error hygiene, redaction and pinned parsing behaviour (T1.3)."""

import asyncio
import gzip
import json
import ssl
import threading
import urllib.parse
from collections.abc import AsyncIterator, Iterator
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
import respx
from contract.adapter_contract import load_openapi_example

from pruefstand.adapters.http import HttpTargetAdapter
from pruefstand.core.config import HttpTargetConfig
from pruefstand.core.errors import ConfigError, TargetError
from pruefstand.core.ids import TenantId
from pruefstand.core.models.target import TargetRequest

BASE = "http://target.test"
REQ = TargetRequest(tenant_id=TenantId("public"), question="Frage", top_k=None, request_id="c-1")
CHUNK = {"chunk_id": "c", "doc_id": "d", "text": "t", "score": 0.5, "rank": 1}


@pytest.fixture
def router() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        yield mock


@pytest.fixture
async def adapter() -> AsyncIterator[HttpTargetAdapter]:
    instance = HttpTargetAdapter(HttpTargetConfig(type="http", url=BASE, timeout_s=5))
    yield instance
    await instance.aclose()


# ---- minors ---------------------------------------------------------------------------------


@pytest.mark.parametrize("url", ["http://127.0.0.1:99999", "http://127.0.0.1:abc"])
def test_bad_ports_are_config_errors(url: str) -> None:
    cfg = HttpTargetConfig.model_construct(type="http", url=url, auth_env=None, timeout_s=5.0)
    with pytest.raises(ConfigError):
        HttpTargetAdapter(cfg)


async def test_unencodable_question_is_a_permanent_target_error(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    req = TargetRequest(tenant_id=TenantId("p"), question="a\ud800b", top_k=None, request_id="r")
    with pytest.raises(TargetError) as excinfo:
        await adapter.query(req)
    assert excinfo.value.transient is False


async def test_exception_groups_and_overflow_become_target_errors(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    router.post("/v1/query").mock(side_effect=ExceptionGroup("g", [OverflowError("port")]))
    with pytest.raises(TargetError) as excinfo:
        await adapter.query(REQ)
    assert excinfo.value.transient is False


async def test_token_is_redacted_in_json_escaped_and_url_encoded_forms(
    router: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = 'ab"c\\d-1234567 xyz'.replace(" ", "_")
    monkeypatch.setenv("TOK5", token)
    body = json.dumps({"error": f"bad {token} and Bearer other-secret-value-99"})
    body += " url=ab%22c%5Cd-1234567_xyz"
    router.post("/v1/query").respond(401, text=body)
    adapter = HttpTargetAdapter(HttpTargetConfig(type="http", url=BASE, auth_env="TOK5"))
    with pytest.raises(TargetError) as excinfo:
        await adapter.query(REQ)
    await adapter.aclose()
    text = str(excinfo.value)
    for leaked in ('ab\\"c', "ab%22c", "1234567", "other-secret-value-99"):
        assert leaked not in text, leaked


def _chain(exc: BaseException | None) -> Iterator[BaseException]:
    seen: set[int] = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        yield exc
        exc = exc.__cause__ or exc.__context__


@pytest.mark.parametrize(
    "content",
    [
        b'{"answer": {"x": "SECRET-ECHO-12345"}}',
        b'{"answer": "SECRET-ECHO-12345"',
        b"SECRET-ECHO-12345",
    ],
)
async def test_no_raw_parser_exception_with_the_input_stays_on_the_chain(
    router: respx.MockRouter, adapter: HttpTargetAdapter, content: bytes
) -> None:
    router.post("/v1/query").respond(200, content=content)
    with pytest.raises(TargetError) as excinfo:
        await adapter.query(REQ)
    for link in _chain(excinfo.value):
        assert not isinstance(link, json.JSONDecodeError)
        assert type(link).__name__ != "ValidationError"
        if "{" in content.decode()[:1] and b"x" in content:
            # a wrong-typed field value is never quoted back (only invalid JSON gets an excerpt)
            assert "SECRET-ECHO-12345" not in f"{link!s} {link!r}"


async def test_bom_content_type_and_duplicate_keys_are_pinned(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    body = b'\xef\xbb\xbf{"answer": "first", "answer": "last"}'
    router.post("/v1/query").respond(200, content=body, headers={"content-type": "text/plain"})
    assert (await adapter.query(REQ)).answer == "last"


async def test_certificate_failures_are_permanent(
    adapter: HttpTargetAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*_: object, **__: object) -> None:
        msg = "tls"
        raise httpx.ConnectError(msg) from ssl.SSLCertVerificationError("self signed")

    # respx drops the cause chain of injected errors, so break the client itself
    monkeypatch.setattr(adapter._client, "stream", fail)
    with pytest.raises(TargetError) as excinfo:
        await adapter.query(REQ)
    assert excinfo.value.transient is False
    assert "certificate" in str(excinfo.value)


async def test_status_is_judged_before_content_encoding(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    route = router.post("/v1/query").respond(
        503, content=gzip.compress(b"junk"), headers={"content-encoding": "gzip"}
    )
    with pytest.raises(TargetError) as excinfo:
        await adapter.query(REQ)
    assert excinfo.value.transient is True
    route.respond(200, content=gzip.compress(b"{}"), headers={"content-encoding": "gzip"})
    with pytest.raises(TargetError) as excinfo2:
        await adapter.query(REQ)
    assert excinfo2.value.transient is False


async def test_info_is_none_only_for_404(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    router.get("/v1/info").respond(405)
    with pytest.raises(TargetError):
        await adapter.info()


TRICKY = 'sec"ret/+&x\\y-9876543'


@pytest.mark.parametrize("status", [200, 401, 500])
async def test_token_is_redacted_in_every_echoed_form(
    router: respx.MockRouter, monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    monkeypatch.setenv("TOK6", TRICKY)
    forms = [
        TRICKY,
        json.dumps(TRICKY)[1:-1],
        json.dumps(json.dumps(TRICKY))[1:-1],
        urllib.parse.quote(TRICKY),
        urllib.parse.quote(TRICKY, safe=""),
        urllib.parse.quote_plus(TRICKY),
    ]
    router.post("/v1/query").respond(status, text="not json: " + " | ".join(forms))
    adapter = HttpTargetAdapter(HttpTargetConfig(type="http", url=BASE, auth_env="TOK6"))
    with pytest.raises(TargetError) as excinfo:
        await adapter.query(REQ)
    await adapter.aclose()
    for form in forms:
        assert form not in str(excinfo.value), form
    assert "9876543" not in str(excinfo.value)


@pytest.mark.parametrize(
    ("citations", "expected"),
    [([1, 2], ("1", "2")), (["§ 1", 7], ("§ 1", "7")), ([], ())],
)
async def test_integer_citation_ids_are_stringified(
    router: respx.MockRouter,
    adapter: HttpTargetAdapter,
    citations: list[object],
    expected: tuple[str, ...],
) -> None:
    router.post("/v1/query").respond(200, json={"answer": "a", "citations": citations})
    assert (await adapter.query(REQ)).citations == expected


@pytest.mark.parametrize("citations", [[True], [1.5], [None], [["x"]], [{"id": 1}]])
async def test_other_non_string_citations_stay_permanent_errors(
    router: respx.MockRouter, adapter: HttpTargetAdapter, citations: list[object]
) -> None:
    router.post("/v1/query").respond(200, json={"answer": "a", "citations": citations})
    with pytest.raises(TargetError) as excinfo:
        await adapter.query(REQ)
    assert excinfo.value.transient is False


async def test_wire_parsing_does_not_use_the_default_executor(
    router: respx.MockRouter,
) -> None:
    loop = asyncio.get_running_loop()
    default = ThreadPoolExecutor(max_workers=1)
    loop.set_default_executor(default)
    release = threading.Event()
    blocker = loop.run_in_executor(None, release.wait)  # occupies the only default worker
    router.post("/v1/query").respond(200, json=load_openapi_example("query_ok.json"))
    adapter = HttpTargetAdapter(HttpTargetConfig(type="http", url=BASE, timeout_s=2))
    try:
        assert (await adapter.query(REQ)).answer.startswith("Einen Monat")
    finally:
        release.set()
        await blocker
        await adapter.aclose()
        default.shutdown(wait=True)
    assert adapter._executor._shutdown
