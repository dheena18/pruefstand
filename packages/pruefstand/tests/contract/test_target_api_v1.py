"""Contract tests for Target API v1: examples, OpenAPI file and pydantic models stay in sync."""

import copy
import os
from collections.abc import Iterator
from typing import Any

import pytest
import respx
from jsonschema import Draft202012Validator
from pydantic import BaseModel

from contract.adapter_contract import (
    EXAMPLES_DIR,
    assert_valid,
    check_adapter_contract,
    load_example,
    load_openapi,
)
from pruefstand.adapters.http import HttpTargetAdapter
from pruefstand.core.config import HttpTargetConfig
from pruefstand.core.ids import TenantId
from pruefstand.core.models.target import (
    RetrievedChunk,
    RetrieveResponse,
    TargetInfo,
    TargetRequest,
    TargetResponse,
    Usage,
)

BASE = "http://target.test"
EXAMPLE_COMPONENT = {
    "query_ok.json": "QueryResponse",
    "query_refused.json": "QueryResponse",
    "query_no_chunks.json": "QueryResponse",
    "query_chunks_no_tenant.json": "QueryResponse",
    "retrieve_ok.json": "RetrieveResponse",
    "info.json": "InfoResponse",
    "health.json": "HealthResponse",
}


def test_every_example_file_is_mapped_and_validates() -> None:
    files = {p.name for p in EXAMPLES_DIR.glob("*.json") if p.name != "_meta.json"}
    assert files == set(EXAMPLE_COMPONENT)
    for name, component in EXAMPLE_COMPONENT.items():
        assert_valid(component, load_example(name))


def test_meta_records_the_origin_of_every_example() -> None:
    meta = load_example("_meta.json")
    assert set(meta) == set(EXAMPLE_COMPONENT)
    assert all(entry["source"] in {"openapi-example", "recorded"} for entry in meta.values())


def test_response_missing_answer_fails() -> None:
    body = copy.deepcopy(load_example("query_ok.json"))
    del body["answer"]
    with pytest.raises(AssertionError, match="answer"):
        assert_valid("QueryResponse", body)


def test_retrieve_response_with_answer_fails() -> None:
    body = {**load_example("retrieve_ok.json"), "answer": "x"}
    with pytest.raises(AssertionError):
        assert_valid("RetrieveResponse", body)


def test_health_with_stats_validates_and_stats_are_optional() -> None:
    assert_valid("HealthResponse", load_example("health.json"))
    assert_valid("HealthResponse", {"status": "ok"})


def test_info_serving_with_integer_counter_fails() -> None:
    body = copy.deepcopy(load_example("info.json"))
    body["serving"]["requests"] = 3
    with pytest.raises(AssertionError):
        assert_valid("InfoResponse", body)


def test_chunk_tenant_and_used_in_prompt_are_optional_and_nullable() -> None:
    chunk = {"chunk_id": "c", "doc_id": "d", "text": "t", "score": 0.5, "rank": 1}
    assert_valid("QueryResponse", {"answer": "a", "citations": [], "chunks": [chunk]})
    nulls = {**chunk, "tenant_id": None, "used_in_prompt": None}
    assert_valid("QueryResponse", {"answer": "a", "chunks": [nulls], "refused": None})


def test_openapi_examples_equal_the_example_files() -> None:
    schemas = load_openapi()["components"]["schemas"]
    first_examples = {
        "QueryResponse": "query_ok.json",
        "RetrieveResponse": "retrieve_ok.json",
        "InfoResponse": "info.json",
        "HealthResponse": "health.json",
    }
    for component, name in first_examples.items():
        assert schemas[component]["examples"][0] == load_example(name), name


def test_openapi_has_no_secret_in_it() -> None:
    text = str(load_openapi()).lower()
    assert "bearer " not in text.replace("scheme: bearer", "")  # no token examples
    assert "authorization:" not in text


def test_openapi_declares_the_four_endpoints() -> None:
    paths = load_openapi()["paths"]
    assert set(paths) == {"/v1/query", "/v1/retrieve", "/v1/info", "/v1/health"}
    assert "post" in paths["/v1/query"]
    assert "post" in paths["/v1/retrieve"]
    assert "get" in paths["/v1/info"]
    assert "get" in paths["/v1/health"]


def _props(schema: dict[str, Any]) -> tuple[set[str], set[str]]:
    return set(schema.get("properties", {})), set(schema.get("required", []))


@pytest.mark.parametrize(
    ("component", "model", "optional"),
    [
        ("QueryRequest", TargetRequest, set()),
        ("RetrievedChunk", RetrievedChunk, {"tenant_id", "used_in_prompt"}),
        ("Usage", Usage, set()),
        ("QueryResponse", TargetResponse, {"citations", "chunks", "refused", "model", "usage"}),
        ("RetrieveResponse", RetrieveResponse, set()),
        ("InfoResponse", TargetInfo, {"serving"}),
    ],
)
def test_openapi_components_match_the_pydantic_models(
    component: str, model: type[BaseModel], optional: set[str]
) -> None:
    api_props, api_required = _props(load_openapi()["components"]["schemas"][component])
    model_props, _ = _props(model.model_json_schema())
    assert api_props == model_props, f"{component} properties drifted from {model.__name__}"
    assert api_required == model_props - optional, f"{component} required set drifted"


@pytest.fixture
def router() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        mock.get("/v1/info").respond(200, json=load_example("info.json"))
        mock.post("/v1/query").respond(200, json=load_example("query_ok.json"))
        mock.post("/v1/retrieve").respond(200, json=load_example("retrieve_ok.json"))
        yield mock


async def test_contract_checker_passes_for_http_adapter(router: respx.MockRouter) -> None:
    adapter = HttpTargetAdapter(HttpTargetConfig(type="http", url=BASE))
    await check_adapter_contract(
        adapter, [("public", "Wie lang ist die Kündigungsfrist?"), ("public", "Und im Probe?")]
    )
    assert router.calls.call_count == 1 + 2 * 2


async def test_contract_checker_passes_for_target_without_optional_endpoints() -> None:
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        mock.get("/v1/info").respond(404)
        mock.post("/v1/retrieve").respond(404)
        mock.post("/v1/query").respond(200, json=load_example("query_no_chunks.json"))
        adapter = HttpTargetAdapter(HttpTargetConfig(type="http", url=BASE))
        await check_adapter_contract(adapter, [("public", "Frage")])


async def test_contract_checker_rejects_rank_gaps() -> None:
    body = copy.deepcopy(load_example("query_ok.json"))
    body["chunks"][1]["rank"] = 3
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        mock.get("/v1/info").respond(404)
        mock.post("/v1/retrieve").respond(404)
        mock.post("/v1/query").respond(200, json=body)
        adapter = HttpTargetAdapter(HttpTargetConfig(type="http", url=BASE))
        with pytest.raises(AssertionError, match="ranks"):
            await check_adapter_contract(adapter, [("public", "Frage")])
        await adapter.aclose()


async def test_adapter_output_serialises_to_the_openapi_query_response() -> None:
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        mock.post("/v1/query").respond(200, json=load_example("query_chunks_no_tenant.json"))
        adapter = HttpTargetAdapter(HttpTargetConfig(type="http", url=BASE))
        request = TargetRequest(
            tenant_id=TenantId("public"), question="q", top_k=None, request_id="x"
        )
        response = await adapter.query(request)
        await adapter.aclose()
    assert_valid("QueryResponse", response.model_dump(mode="json"))
    assert response.chunks is not None
    assert response.chunks[0].tenant_id is None


@pytest.mark.live
async def test_contract_live() -> None:
    url = os.environ.get("PRUEFSTAND_TARGET_URL")
    if not url:
        pytest.skip("PRUEFSTAND_TARGET_URL is not set (T1.13 runs this against the real rag-demo)")
    adapter = HttpTargetAdapter(HttpTargetConfig(type="http", url=url, timeout_s=120))
    await check_adapter_contract(adapter, [("kanzlei_mueller", "Wie lang ist die Kündigungsfrist?")])


def test_openapi_file_is_openapi_31_with_valid_json_schemas() -> None:
    spec = load_openapi()
    assert str(spec["openapi"]).startswith("3.1")
    for name, schema in spec["components"]["schemas"].items():
        Draft202012Validator.check_schema(schema)
        assert schema.get("additionalProperties") is False or name == "Stats", name
