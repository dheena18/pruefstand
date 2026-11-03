"""Builds the collaborators of one app instance for the ``live`` and the ``gpu`` profile."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rag_demo.analysis.analyzer import GermanAnalyzer
from rag_demo.analysis.fingerprint import fingerprint
from rag_demo.analysis.sparse import SparseEncoder
from rag_demo.catalogue import CatalogueEntry, check_against_catalogue, load_catalogue
from rag_demo.config import Settings, resolve_model_sha
from rag_demo.endpoints import check_endpoint, resolve_endpoint
from rag_demo.errors import ConfigError
from rag_demo.generate import OpenAICompatGenerator
from rag_demo.generate_ollama import OllamaChatGenerator
from rag_demo.index.encoders import OllamaDenseEncoder, TeiDenseEncoder
from rag_demo.index.tokens import load_token_counter
from rag_demo.models import RagConfig, Stats
from rag_demo.protocols import DenseEncoder, Generator, Reranker
from rag_demo.retrieval.corpus_meta import CorpusMeta
from rag_demo.retrieval.rerank import CrossEncoderReranker, IdentityReranker
from rag_demo.retrieval.retriever import QdrantRetriever
from rag_demo.retrieval.store import QdrantStore


@dataclass(frozen=True)
class Urls:
    """The service URLs of one instance."""

    llm: str
    embed: str


def resolve_embed_url(cfg: RagConfig, settings: Settings) -> str:
    """The embedding URL: ``EMBED_URL`` for ``live``, the checked variable for ``gpu``.

    Raises:
        ConfigError: ``gpu`` profile and the endpoint variable is unset or breaks the rules.
    """
    e = cfg.embed
    if cfg.profile != "gpu":
        check_endpoint(settings.embed_url, engine=e.engine)
        return settings.embed_url
    return resolve_endpoint(base_url=e.base_url, endpoint_env=e.endpoint_env, engine=e.engine)


def resolve_urls(cfg: RagConfig, settings: Settings) -> Urls:
    """The generator and embedding URLs: settings for ``live``, checked env variables for ``gpu``.

    Raises:
        ConfigError: ``gpu`` profile and an endpoint variable is unset or breaks the endpoint
            rules (the message names the variable).
    """
    g = cfg.generator
    if cfg.profile != "gpu":
        check_endpoint(settings.llm_url, engine=g.engine)
    llm = (
        settings.llm_url
        if cfg.profile != "gpu"
        else resolve_endpoint(base_url=g.base_url, endpoint_env=g.endpoint_env, engine=g.engine)
    )
    return Urls(llm=llm, embed=resolve_embed_url(cfg, settings))


def build_catalogue(cfg: RagConfig, settings: Settings) -> dict[str, CatalogueEntry] | None:
    """The catalogue for the ``gpu`` profile (``None`` for ``live``).

    Raises:
        ConfigError: ``gpu`` profile without ``RAG_MODEL_CATALOGUE``, an unreadable file, or a
            config that disagrees with it (so a config built in code fails at startup too).
    """
    if cfg.profile != "gpu":
        return None
    if settings.rag_model_catalogue is None:
        msg = "profile gpu needs the model catalogue: set RAG_MODEL_CATALOGUE"
        raise ConfigError(msg)
    catalogue = load_catalogue(settings.rag_model_catalogue)
    check_against_catalogue(cfg, catalogue, settings.rag_model_catalogue)
    return catalogue


def build_generator(cfg: RagConfig, url: str, stats: Stats) -> Generator:
    """The generator class for ``cfg.generator.engine``."""
    if cfg.generator.engine == "ollama":
        return OllamaChatGenerator(cfg, url, stats=stats)
    return OpenAICompatGenerator(cfg, url, stats=stats)


def build_analyzer(cfg: RagConfig) -> GermanAnalyzer:
    """The analyzer of ``cfg.analyzer`` (identical at index and query time)."""
    a = cfg.analyzer
    return GermanAnalyzer(a.compound_split, a.stemmer, a.fold_umlauts)


def expected_fingerprint(cfg: RagConfig) -> dict[str, Any]:
    """The index fingerprint this app instance can query (see ``analysis.fingerprint``)."""
    return fingerprint(build_analyzer(cfg), SparseEncoder())


_INTEGER_OPTIONS = frozenset({"num_ctx", "num_predict", "seed"})


def catalogue_options(
    cfg: RagConfig, catalogue: dict[str, CatalogueEntry] | None
) -> dict[str, int | float] | None:
    """The catalogue ``options`` of the embedding model, or ``None`` without a catalogue entry.

    They are sent as they are, so Ollama keeps the model loaded instead of reloading it.
    """
    entry = catalogue.get(cfg.embed.catalogue_id or "") if catalogue else None
    if entry is None:
        return None
    return {k: int(v) if k in _INTEGER_OPTIONS else v for k, v in entry.options.items()}


def build_dense(
    cfg: RagConfig,
    url: str,
    *,
    catalogue: dict[str, CatalogueEntry] | None = None,
    tokenizer: Path | None = None,
) -> DenseEncoder:
    """The dense encoder of ``cfg.embed.engine`` (TEI for tier 1, Ollama ``/api/embed`` for tier 2).

    Args:
        cfg: The configuration.
        url: Embedding service base URL.
        catalogue: The checked catalogue (``gpu`` profile); its options are sent to Ollama.
        tokenizer: The model's ``tokenizer.json`` for the truncation counter (Ollama only).

    Raises:
        ConfigError: The tokenizer file is configured but unusable.
    """
    if cfg.embed.engine != "ollama":
        return TeiDenseEncoder(cfg.embed, url)
    counter = load_token_counter(tokenizer) if tokenizer else None
    return OllamaDenseEncoder(
        cfg.embed, url, options=catalogue_options(cfg, catalogue), count_tokens=counter
    )


RERANK_PASSAGE_TOKENS = 256
RERANK_TIMEOUT_S = 60.0


def build_reranker(cfg: RagConfig, catalogue: dict[str, CatalogueEntry] | None = None) -> Reranker:
    """``IdentityReranker`` for ``reranker: off``, else ``CrossEncoderReranker`` on ``rerank-cpu``.

    The URL is the checked ``rerank.base_url`` or the variable ``rerank.endpoint_env``
    (``RERANK_URL``); the passage limit and the timeout come from the catalogue entry with the
    role ``rerank`` (256 tokens, CPU-sized timeout) when there is a catalogue.

    Raises:
        ConfigError: ``reranker: on`` and the URL variable is unset or breaks the endpoint rules.
    """
    if cfg.reranker == "off":
        return IdentityReranker()
    r = cfg.rerank
    url = resolve_endpoint(base_url=r.base_url, endpoint_env=r.endpoint_env, engine="cpu")
    entry = next((e for e in (catalogue or {}).values() if e.role == "rerank"), None)
    tokens = entry.max_input_tokens if entry else None
    timeout = entry.request_timeout_s if entry else None
    return CrossEncoderReranker(
        url,
        max_passage_tokens=tokens or RERANK_PASSAGE_TOKENS,
        timeout_s=timeout or RERANK_TIMEOUT_S,
    )


def qdrant_key(settings: Settings) -> str | None:
    """The Qdrant API key (``QDRANT_API_KEY``) or ``None``."""
    return settings.qdrant_api_key.get_secret_value() if settings.qdrant_api_key else None


def build_store(settings: Settings) -> QdrantStore:
    """The Qdrant client of the served collection, with the API key when one is set."""
    return QdrantStore(settings.qdrant_url, settings.collection, api_key=qdrant_key(settings))


def build_corpus(
    cfg: RagConfig, settings: Settings, store: QdrantStore | None = None
) -> CorpusMeta:
    """The checked collection metadata (complete index, same analyzer fingerprint as the app)."""
    return CorpusMeta(store or build_store(settings), expected_fingerprint(cfg))


def build_retriever(
    cfg: RagConfig,
    settings: Settings,
    embed_url: str,
    catalogue: dict[str, CatalogueEntry] | None = None,
    *,
    corpus: CorpusMeta | None = None,
) -> QdrantRetriever:
    """The retriever with the dense encoder of ``cfg.embed.engine`` and the configured reranker."""
    encoder = build_dense(cfg, embed_url, catalogue=catalogue, tokenizer=settings.embed_tokenizer)
    store = build_store(settings)
    return QdrantRetriever(
        cfg,
        store=store,
        corpus=corpus or build_corpus(cfg, settings, store),
        dense=encoder,
        analyzer=build_analyzer(cfg),
        sparse=SparseEncoder(),
        reranker=build_reranker(cfg, catalogue),
    )


def info_env(settings: Settings) -> dict[str, str]:
    """The static values ``/v1/info`` reports besides the config."""
    return {
        "GIT_SHA": settings.git_sha,
        "IMAGE_DIGEST": settings.image_digest or "",
        "LLAMA_CPP_VERSION": settings.llama_cpp_version,
        "MODEL_SHA256": resolve_model_sha(settings),
        "SERVING_ENGINE_VERSION": settings.serving_engine_version,
        "SERVING_GPU": settings.serving_gpu,
    }
