"""Shared models of rag-demo: the configuration, retrieval hits, generator output (single home)."""

from dataclasses import dataclass
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rag_demo.endpoints import check_endpoint, check_served

CANDIDATE_KEY_ENV = "PRUEFSTAND_CANDIDATE_API_KEY"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class GeneratorCfg(_Frozen):
    """The generator model: llama.cpp (tier 1, OpenAI-compatible) or Ollama (tier 2, native API).

    ``api_key_env`` names the environment variable holding the bearer key (D216); when it is
    unset or empty no ``Authorization`` header is sent. ``enable_thinking`` is part of the config
    hash (D95); for Qwen3 families it is sent as ``chat_template_kwargs.enable_thinking``.
    Tier 2: ``catalogue_id`` (``ollama/<tag>``, D221) names the catalogue entry, ``model`` is the
    bare tag, ``endpoint_env`` the variable holding the URL (read at app start), ``options`` the
    load-time options that must equal the catalogue (``num_ctx``, ``top_p``).
    """

    model: str
    family: str
    enable_thinking: bool = False
    api_key_env: str | None = CANDIDATE_KEY_ENV
    temperature: float = 0.0
    seed: int = 0
    engine: Literal["llama.cpp", "ollama"] = "llama.cpp"
    catalogue_id: str | None = None
    endpoint_env: str | None = None
    base_url: str | None = None
    options: dict[str, int | float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _served(self) -> Self:
        check_served(
            engine=self.engine,
            catalogue_id=self.catalogue_id,
            endpoint_env=self.endpoint_env,
            base_url=self.base_url,
            options=self.options,
        )
        if self.engine == "ollama" and self.enable_thinking:
            msg = "Qwen3 thinking is always disabled (think: false); enable_thinking must be false"
            raise ValueError(msg)
        return self


class EmbedCfg(_Frozen):
    """The embedding model: TEI (tier 1) or Ollama ``/api/embed`` (tier 2); see ``GeneratorCfg``."""

    model: str
    query_prefix: str = ""
    doc_prefix: str = ""
    max_input_tokens: int = 512
    dim: int = 384
    api_key_env: str | None = CANDIDATE_KEY_ENV
    engine: Literal["tei", "ollama"] = "tei"
    catalogue_id: str | None = None
    endpoint_env: str | None = None
    base_url: str | None = None
    options: dict[str, int | float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _served(self) -> Self:
        check_served(
            engine=self.engine,
            catalogue_id=self.catalogue_id,
            endpoint_env=self.endpoint_env,
            base_url=self.base_url,
            options=self.options,
        )
        return self


class RerankCfg(_Frozen):
    """The reranker placeholder (T3.5 fills it); ``rerank-cpu`` has no auth, so no key (D217)."""

    enabled: bool = False
    endpoint_env: str | None = "RERANK_URL"
    base_url: str | None = None

    @model_validator(mode="after")
    def _endpoint(self) -> Self:
        if self.base_url is not None:
            check_endpoint(self.base_url, engine="cpu")
        return self


class GenerationCfg(_Frozen):
    """Sampling options sent to Ollama: ``temperature``, ``seed``, ``num_predict`` (R12 N2)."""

    temperature: float = 0.0
    seed: int = 1234
    max_tokens: int = Field(ge=1)


class AnalyzerCfg(_Frozen):
    """The German analyzer switches (T3.3); part of ``config_hash`` (the run identity).

    The index is protected separately: the Indexer writes an analyzer fingerprint into the
    collection metadata and the app refuses a collection whose fingerprint differs (503).

    ``compound_split: false`` is mutation M4 (compound words stay one token).
    """

    compound_split: bool = True
    fold_umlauts: bool = True
    stemmer: Literal["snowball_de", "none"] = "snowball_de"


class RagConfig(_Frozen):
    """``configs/rag.yaml``; the bug switches default to the correct behaviour (interfaces §16)."""

    profile: Literal["live", "gpu"] = "live"
    generator: GeneratorCfg
    embed: EmbedCfg
    rerank: RerankCfg = Field(default_factory=RerankCfg)
    analyzer: AnalyzerCfg = Field(default_factory=AnalyzerCfg)
    generation: GenerationCfg | None = None
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

    @model_validator(mode="after")
    def _ollama_generation(self) -> Self:
        if self.generator.engine != "ollama":
            return self
        if self.generation is None:
            msg = "generation (temperature, seed, max_tokens) is required for engine ollama"
            raise ValueError(msg)
        if self.generation.max_tokens != self.max_tokens:
            msg = "generation.max_tokens must equal max_tokens (one value, sent as num_predict)"
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
