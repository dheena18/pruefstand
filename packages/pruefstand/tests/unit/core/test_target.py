import json
from typing import Any

import pytest
from pydantic import ValidationError

from pruefstand.core.ids import CaseId, TenantId
from pruefstand.core.models.target import (
    CaseRecord,
    RetrievedChunk,
    RetrieveResponse,
    TargetInfo,
    TargetRequest,
    TargetResponse,
    Usage,
)

CHUNK: dict[str, Any] = {
    "chunk_id": "bgb-622#0",
    "doc_id": "bgb-622",
    "tenant_id": "kanzlei_mueller",
    "text": "Das Arbeitsverhältnis kann mit einer Frist von vier Wochen gekündigt werden.",
    "score": 0.83,
    "rank": 1,
}

QUERY_JSON = {
    "answer": "Einen Monat (§ 622 Abs. 2 BGB).",
    "citations": ["§ 622 Abs. 2 BGB"],
    "chunks": None,
    "refused": None,
    "model": None,
    "usage": {"prompt_tokens": 812, "completion_tokens": 41},
}


def test_target_response_from_interfaces_example() -> None:
    resp = TargetResponse.model_validate(QUERY_JSON)
    assert resp.chunks is None
    assert resp.refused is None
    assert resp.usage == Usage(prompt_tokens=812, completion_tokens=41)
    assert resp.citations == ("§ 622 Abs. 2 BGB",)


def test_target_response_minimal() -> None:
    resp = TargetResponse.model_validate({"answer": "x"})
    assert resp.citations == ()
    assert resp.chunks is None


def test_chunk_without_tenant_is_allowed_when_null() -> None:
    chunk = RetrievedChunk.model_validate({**CHUNK, "tenant_id": None})
    assert chunk.tenant_id is None


def test_used_in_prompt_defaults_to_none() -> None:
    assert RetrievedChunk.model_validate(CHUNK).used_in_prompt is None
    assert RetrievedChunk.model_validate({**CHUNK, "used_in_prompt": True}).used_in_prompt is True


def test_extra_fields_are_errors() -> None:
    with pytest.raises(ValidationError, match="extra"):
        RetrievedChunk.model_validate({**CHUNK, "x": 1})
    with pytest.raises(ValidationError, match="extra"):
        TargetResponse.model_validate({"answer": "x", "x": 1})
    with pytest.raises(ValidationError, match="extra"):
        TargetRequest.model_validate({"tenant_id": "t", "question": "q", "request_id": "r", "x": 1})


def test_request_top_k_optional() -> None:
    req = TargetRequest(tenant_id=TenantId("t"), question="Frage?", request_id="r1")
    assert req.top_k is None


def test_target_info_serving_round_trip() -> None:
    info = TargetInfo(
        app_version="0.1",
        git_sha="abc",
        image_digest=None,
        config_hash="cfg",
        corpus_version="2026-11-02.ab12cd34",
        models={"generator": "ollama/qwen3.8:27b-q8_0"},
        serving={"engine": "ollama", "quantization": "Q8_0"},
    )
    assert TargetInfo.model_validate_json(info.model_dump_json()) == info
    assert TargetInfo.model_validate_json(info.model_dump_json()).serving["quantization"] == "Q8_0"


def test_target_info_serving_defaults_to_empty() -> None:
    data: dict[str, Any] = {
        "app_version": "0.1",
        "git_sha": "abc",
        "image_digest": None,
        "config_hash": "c",
        "corpus_version": "v",
        "models": {},
    }
    assert TargetInfo.model_validate(data).serving == {}


def record(**changes: Any) -> CaseRecord:
    data: dict[str, Any] = {
        "case_id": CaseId("law-0042"),
        "request": {"tenant_id": "kanzlei_mueller", "question": "Frage?", "request_id": "r"},
        "response": None,
        "error": None,
        "latency_ms": 12.5,
        "cached": False,
        "attempt": 1,
    }
    return CaseRecord.model_validate({**data, **changes})


def test_case_record_with_error_round_trip() -> None:
    rec = record(error="timeout")
    assert rec.response is None
    assert CaseRecord.model_validate_json(rec.model_dump_json()) == rec


def test_case_record_mode() -> None:
    assert record().mode == "answer"
    rec = record(mode="retrieve", response={"answer": ""})
    assert CaseRecord.model_validate_json(rec.model_dump_json()).mode == "retrieve"
    with pytest.raises(ValidationError, match="mode"):
        record(mode="generate")


def test_retrieve_response_from_interfaces_example() -> None:
    body = json.loads(json.dumps({"chunks": [CHUNK]}))
    resp = RetrieveResponse.model_validate(body)
    assert [c.rank for c in resp.chunks] == [1]
    with pytest.raises(ValidationError, match="extra"):
        RetrieveResponse.model_validate({"chunks": [], "answer": "x"})


def test_chunk_with_absent_tenant_id_parses_through_target_response() -> None:
    chunk = {k: v for k, v in CHUNK.items() if k != "tenant_id"}
    resp = TargetResponse.model_validate({"answer": "x", "chunks": [chunk]})
    assert resp.chunks is not None
    assert resp.chunks[0].tenant_id is None
    explicit = TargetResponse.model_validate(
        {"answer": "x", "chunks": [{**chunk, "tenant_id": None}]}
    )
    assert explicit.chunks is not None
    assert explicit.chunks[0].tenant_id is None
