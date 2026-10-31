"""Models of the target HTTP API v1 and of one recorded exchange (interfaces §1.1, §2)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from pruefstand.core.ids import CaseId, ChunkId, DocId, TenantId


class TargetRequest(BaseModel):
    """Body of ``POST /v1/query`` and ``POST /v1/retrieve``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tenant_id: TenantId
    question: str
    top_k: int | None = None
    request_id: str


class RetrievedChunk(BaseModel):
    """One retrieved chunk as reported by the target.

    ``used_in_prompt`` (API v1, backward compatible) is ``True`` when the chunk was in the
    generator prompt; ``None`` when the target does not say.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    chunk_id: ChunkId
    doc_id: DocId
    tenant_id: TenantId | None
    text: str
    score: float
    rank: int
    used_in_prompt: bool | None = None


class Usage(BaseModel):
    """Token usage reported by the target."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    prompt_tokens: int
    completion_tokens: int


class TargetResponse(BaseModel):
    """Response of ``POST /v1/query``; optional fields may be omitted by third-party targets."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    answer: str
    citations: tuple[str, ...] = ()
    chunks: tuple[RetrievedChunk, ...] | None = None
    refused: bool | None = None
    model: str | None = None
    usage: Usage | None = None


class RetrieveResponse(BaseModel):
    """Response of ``POST /v1/retrieve``: retrieval only, no answer (R11 D218)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    chunks: tuple[RetrievedChunk, ...]


class TargetInfo(BaseModel):
    """Response of ``GET /v1/info``.

    ``serving`` holds static fields only (engine, engine_version, quantization, gpu,
    model_sha256); runtime counters of ``/v1/health.stats`` never enter this model.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    app_version: str
    git_sha: str
    image_digest: str | None
    config_hash: str
    corpus_version: str
    models: dict[str, str]
    serving: dict[str, str] = {}


class CaseRecord(BaseModel):
    """One case's exchange with the target (one line of ``responses.jsonl``).

    ``mode="retrieve"`` marks a ``robust_pr`` case sent to ``/v1/retrieve``; its response has
    ``answer == ""`` and answer metrics are ``not_applicable`` (R11 D218, D222).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: CaseId
    request: TargetRequest
    response: TargetResponse | None
    error: str | None
    latency_ms: float
    cached: bool
    attempt: int
    mode: Literal["answer", "retrieve"] = "answer"
