"""Wire models of Target HTTP API v1 (they generate ``schemas/target-api-v1.openapi.yaml``)."""

from pydantic import BaseModel, ConfigDict, Field


class QueryRequest(BaseModel):
    """Body of ``POST /v1/query``; strict, unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    question: str = Field(min_length=1, max_length=2000)
    top_k: int | None = Field(default=None, ge=1, le=50)
    request_id: str


class RetrievedChunk(BaseModel):
    """One chunk of the answer's context."""

    chunk_id: str
    doc_id: str
    tenant_id: str | None = None
    text: str
    score: float
    rank: int = Field(ge=1)
    used_in_prompt: bool | None = None


class Usage(BaseModel):
    """Token usage of the generator call."""

    prompt_tokens: int
    completion_tokens: int


class QueryResponse(BaseModel):
    """Body of the ``/v1/query`` answer."""

    answer: str
    citations: list[str] = Field(default_factory=list)
    chunks: list[RetrievedChunk] | None = None
    refused: bool | None = None
    model: str | None = None
    usage: Usage | None = None


class InfoResponse(BaseModel):
    """Body of ``GET /v1/info``: static fields only (X3.13)."""

    app_version: str
    git_sha: str
    image_digest: str | None
    config_hash: str
    corpus_version: str
    models: dict[str, str]
    serving: dict[str, str] = Field(default_factory=dict)


class Stats(BaseModel):
    """Runtime counters of ``/v1/health``."""

    think_stripped: int = 0
    truncated_chunks: int = 0
    requests: int = 0


class HealthResponse(BaseModel):
    """Body of ``GET /v1/health``."""

    status: str
    stats: Stats | None = None
