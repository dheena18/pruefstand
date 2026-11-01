"""Shared models of rag-demo: the configuration, retrieval hits, generator output (single home)."""

from dataclasses import dataclass
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

CANDIDATE_KEY_ENV = "PRUEFSTAND_CANDIDATE_API_KEY"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class GeneratorCfg(_Frozen):
    """The generator model (llama.cpp, OpenAI-compatible chat API).

    ``api_key_env`` names the environment variable holding the bearer key (D216); when it is
    unset or empty no ``Authorization`` header is sent. ``enable_thinking`` is part of the config
    hash (D95); for Qwen3 families it is sent as ``chat_template_kwargs.enable_thinking``.
    """

    model: str
    family: str
    enable_thinking: bool = False
    api_key_env: str | None = CANDIDATE_KEY_ENV
    temperature: float = 0.0
    seed: int = 0


class EmbedCfg(_Frozen):
    """The embedding model (TEI): prefixes, input limit and vector size from the model pin."""

    model: str
    query_prefix: str = ""
    doc_prefix: str = ""
    max_input_tokens: int = 512
    dim: int = 384
    api_key_env: str | None = CANDIDATE_KEY_ENV


class RagConfig(_Frozen):
    """``configs/rag.yaml``; the bug switches default to the correct behaviour (interfaces §16)."""

    generator: GeneratorCfg
    embed: EmbedCfg
    top_k: int = Field(default=8, ge=1, le=50)
    chunk_prompt_tokens: int = Field(default=256, ge=16)
    max_tokens: int = Field(default=256, ge=16)
    tenant_filter: Literal["inside", "post_topk"] = "inside"
    shared_public_merge: Literal["filtered", "unfiltered"] = "filtered"
    reranker: Literal["on", "off"] = "off"
    answer_language: Literal["auto", "en"] = "auto"
    prompt_file: str = "prompts/answer_de_v1.txt"
    injection_guard: Literal["on", "off"] = "on"
    system_prompt_guard: Literal["on", "off"] = "on"

    @model_validator(mode="after")
    def _no_reranker_yet(self) -> Self:
        if self.reranker == "on":
            msg = "reranker 'on' arrives with T3.5; v0 has no reranker"
            raise ValueError(msg)
        return self


class SparseVector(_Frozen):
    """A sparse vector: strictly increasing hashed term indices and their BM25 weights."""

    indices: list[int]
    values: list[float]


@dataclass(frozen=True)
class QueryVectors:
    """The query embedded for both retrieval legs."""

    dense: list[float]
    sparse: SparseVector


class Hit(_Frozen):
    """One retrieved chunk. ``tenant_id`` is the corpus ``tenant`` of the chunk."""

    chunk_id: str
    doc_id: str
    tenant_id: str
    text: str
    score: float
    rank: int
    citation_key: str | None = None
    section: str | None = None


class GenOutput(_Frozen):
    """The generator's answer and which chunks entered its prompt (X3.14)."""

    answer: str
    citations: list[str]
    refused: bool
    model: str
    prompt_tokens: int
    completion_tokens: int
    prompt_chunk_ids: list[str]


@dataclass
class Stats:
    """Runtime counters of ``/v1/health``; never part of any fingerprint (X3.13)."""

    think_stripped: int = 0
    truncated_chunks: int = 0
    requests: int = 0
