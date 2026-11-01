import json
import logging
from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
import respx
from contract.adapter_contract import load_example

from pruefstand.adapters.http import HttpTargetAdapter
from pruefstand.core.config import HttpTargetConfig
from pruefstand.core.errors import TargetError
from pruefstand.core.ids import TenantId
from pruefstand.core.models.target import TargetRequest

BASE = "http://target.test"
QUESTION = "Wie lang ist die Kündigungsfrist?"


def request(case_id: str = "case-0001") -> TargetRequest:
    # the runner may (wrongly) put the case id here; the adapter must never send it
    return TargetRequest(
        tenant_id=TenantId("public"), question=QUESTION, top_k=3, request_id=case_id
    )


@pytest.fixture
def router() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        yield mock


@pytest.fixture
async def adapter() -> AsyncIterator[HttpTargetAdapter]:
    instance = HttpTargetAdapter(HttpTargetConfig(type="http", url=BASE, timeout_s=5))
    yield instance
    await instance.aclose()


async def test_query_ok_parses_answer_citations_and_chunks(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    router.post("/v1/query").respond(200, json=load_example("query_ok.json"))
    response = await adapter.query(request())
    assert response.answer == "Einen Monat zum Ende eines Kalendermonats (§ 622 Abs. 2 Nr. 1 BGB)."
    assert response.citations == ("§ 622 Abs. 2 Nr. 1 BGB",)
    assert response.chunks is not None
    assert response.chunks[0].doc_id == "gii-bgb-622"
    assert response.chunks[0].used_in_prompt is True
    assert response.chunks[1].used_in_prompt is None


async def test_query_without_chunks_gives_none(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    router.post("/v1/query").respond(200, json=load_example("query_no_chunks.json"))
    assert (await adapter.query(request())).chunks is None


async def test_chunk_without_tenant_id_parses(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    router.post("/v1/query").respond(200, json=load_example("query_chunks_no_tenant.json"))
    response = await adapter.query(request())
    assert response.chunks is not None
    assert response.chunks[0].tenant_id is None


async def test_refused_example_parses(router: respx.MockRouter, adapter: HttpTargetAdapter) -> None:
    router.post("/v1/query").respond(200, json=load_example("query_refused.json"))
    response = await adapter.query(request())
    assert response.refused is True
    assert response.chunks == ()


@pytest.mark.parametrize(
    ("status", "transient"), [(503, True), (500, True), (400, False), (404, False), (422, False)]
)
async def test_http_errors_map_to_transient_flag(
    router: respx.MockRouter,
    adapter: HttpTargetAdapter,
    status: int,
    transient: bool,  # noqa: FBT001
) -> None:
    router.post("/v1/query").respond(status, text="boom")
    with pytest.raises(TargetError) as excinfo:
        await adapter.query(request())
    assert excinfo.value.transient is transient
    assert str(status) in str(excinfo.value)


async def test_timeout_is_transient(router: respx.MockRouter, adapter: HttpTargetAdapter) -> None:
    router.post("/v1/query").mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(TargetError) as excinfo:
        await adapter.query(request())
    assert excinfo.value.transient is True


async def test_connection_error_is_transient(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    router.post("/v1/query").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(TargetError) as excinfo:
        await adapter.query(request())
    assert excinfo.value.transient is True


async def test_invalid_json_is_permanent_with_short_excerpt(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    router.post("/v1/query").respond(200, text="<html>" + "x" * 5000)
    with pytest.raises(TargetError) as excinfo:
        await adapter.query(request())
    assert excinfo.value.transient is False
    assert "<html>" in str(excinfo.value)
    assert "x" * 201 not in str(excinfo.value)


async def test_schema_violation_is_permanent(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    router.post("/v1/query").respond(200, json={"citations": []})
    with pytest.raises(TargetError) as excinfo:
        await adapter.query(request())
    assert excinfo.value.transient is False


async def test_auth_header_sent_and_secret_never_logged(
    router: respx.MockRouter,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capfd: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("T", "s3cr3t-value-123456")
    route = router.post("/v1/query").respond(200, json=load_example("query_ok.json"))
    adapter = HttpTargetAdapter(HttpTargetConfig(type="http", url=BASE, auth_env="T"))
    with caplog.at_level(logging.DEBUG):
        await adapter.query(request())
        router.post("/v1/query").respond(500, text="nope")
        with pytest.raises(TargetError) as excinfo:
            await adapter.query(request())
    await adapter.aclose()
    assert route.calls[0].request.headers["authorization"] == "Bearer s3cr3t-value-123456"
    out = capfd.readouterr()
    for blob in (caplog.text, out.out, out.err, str(excinfo.value), repr(excinfo.value)):
        assert "s3cr3t-value-123456" not in blob


async def test_no_auth_header_without_auth_env(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    route = router.post("/v1/query").respond(200, json=load_example("query_ok.json"))
    await adapter.query(request())
    assert "authorization" not in route.calls[0].request.headers


async def test_info_404_is_none(router: respx.MockRouter, adapter: HttpTargetAdapter) -> None:
    router.get("/v1/info").respond(404)
    assert await adapter.info() is None


async def test_info_example_has_static_serving_fields_only(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    router.get("/v1/info").respond(200, json=load_example("info.json"))
    info = await adapter.info()
    assert info is not None
    assert info.serving["engine"] == "llama.cpp"
    assert not {"think_stripped", "truncated_chunks", "requests"} & set(info.serving)


async def test_info_server_error_raises(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    router.get("/v1/info").respond(503)
    with pytest.raises(TargetError) as excinfo:
        await adapter.info()
    assert excinfo.value.transient is True


async def test_request_ids_are_random_and_never_the_case_id(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    route = router.post("/v1/query").respond(200, json=load_example("query_ok.json"))
    await adapter.query(request("case-0001"))
    await adapter.query(request("case-0001"))
    bodies = [json.loads(call.request.content) for call in route.calls]
    ids = [b["request_id"] for b in bodies]
    assert ids[0] != ids[1]
    assert "case-0001" not in ids
    assert all(len(i) == 32 and int(i, 16) >= 0 for i in ids)
    assert all("case-0001" not in call.request.content.decode() for call in route.calls)
    assert set(bodies[0]) == {"tenant_id", "question", "top_k", "request_id"}
    assert bodies[0]["question"] == QUESTION


async def test_retrieve_ok_sends_same_body_shape_to_v1_retrieve(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    route = router.post("/v1/retrieve").respond(200, json=load_example("retrieve_ok.json"))
    response = await adapter.retrieve(request())
    assert response is not None
    assert [c.rank for c in response.chunks] == [1, 2]
    sent = json.loads(route.calls[0].request.content)
    assert set(sent) == {"tenant_id", "question", "top_k", "request_id"}
    assert sent["request_id"] != "case-0001"


@pytest.mark.parametrize("status", [404, 405])
async def test_retrieve_missing_endpoint_is_none(
    router: respx.MockRouter, adapter: HttpTargetAdapter, status: int
) -> None:
    router.post("/v1/retrieve").respond(status)
    assert await adapter.retrieve(request()) is None


async def test_retrieve_503_is_transient(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    router.post("/v1/retrieve").respond(503)
    with pytest.raises(TargetError) as excinfo:
        await adapter.retrieve(request())
    assert excinfo.value.transient is True


async def test_retrieve_response_with_answer_is_permanent_error(
    router: respx.MockRouter, adapter: HttpTargetAdapter
) -> None:
    body = {**load_example("retrieve_ok.json"), "answer": "generated although not allowed"}
    router.post("/v1/retrieve").respond(200, json=body)
    with pytest.raises(TargetError) as excinfo:
        await adapter.retrieve(request())
    assert excinfo.value.transient is False
    assert "answer" in str(excinfo.value)


async def test_aclose_is_idempotent_and_query_after_close_raises(
    router: respx.MockRouter,
) -> None:
    adapter = HttpTargetAdapter(HttpTargetConfig(type="http", url=BASE))
    await adapter.aclose()
    await adapter.aclose()
    with pytest.raises(TargetError):
        await adapter.query(request())


async def test_base_url_with_path_prefix_is_kept(router: respx.MockRouter) -> None:
    route = router.post("/api/rag/v1/query").respond(200, json=load_example("query_ok.json"))
    adapter = HttpTargetAdapter(HttpTargetConfig(type="http", url=BASE + "/api/rag/"))
    await adapter.query(request())
    await adapter.aclose()
    assert route.call_count == 1
