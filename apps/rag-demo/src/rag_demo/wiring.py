"""Builds the collaborators of one app instance for the ``live`` and the ``gpu`` profile."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
from numpy.typing import NDArray

from rag_demo.analysis.analyzer import GermanAnalyzer
from rag_demo.analysis.fingerprint import fingerprint
from rag_demo.analysis.sparse import SparseEncoder
from rag_demo.catalogue import CatalogueEntry, check_against_catalogue, load_catalogue
from rag_demo.config import Settings, resolve_model_sha
from rag_demo.dense import TeiDenseEncoder
from rag_demo.endpoints import check_endpoint, resolve_endpoint
from rag_demo.errors import ConfigError, EmbeddingError
from rag_demo.generate import OpenAICompatGenerator
from rag_demo.generate_ollama import OllamaChatGenerator
from rag_demo.models import RagConfig, Stats
from rag_demo.protocols import DenseEncoder, Generator
from rag_demo.retrieve import Retriever


class PendingOllamaEncoder:
    """Placeholder for ``embed.engine: ollama`` until T3.4 adds ``OllamaDenseEncoder``.

    The app starts and serves ``/v1/info``; every ``encode`` call fails with ``EmbeddingError``
    (the API maps it to 503), so no query is answered with a wrong embedding.
    """

    truncated = 0

    def encode(
        self, texts: Sequence[str], kind: Literal["query", "passage"] = "query"
    ) -> NDArray[np.float32]:
        """Always raise: Ollama embeddings arrive with T3.4.

        Raises:
            EmbeddingError: Always.
        """
        del texts, kind
        msg = "Ollama embeddings (/api/embed) arrive with T3.4"
        raise EmbeddingError(msg)


@dataclass(frozen=True)
class Urls:
    """The service URLs of one instance."""

    llm: str
    embed: str


def resolve_urls(cfg: RagConfig, settings: Settings) -> Urls:
    """The generator and embedding URLs: settings for ``live``, checked env variables for ``gpu``.

    Raises:
        ConfigError: ``gpu`` profile and an endpoint variable is unset or breaks the endpoint
            rules (the message names the variable).
    """
    if cfg.profile != "gpu":
        check_endpoint(settings.llm_url, engine=cfg.generator.engine)
        check_endpoint(settings.embed_url, engine=cfg.embed.engine)
        return Urls(llm=settings.llm_url, embed=settings.embed_url)
    g, e = cfg.generator, cfg.embed
    return Urls(
        llm=resolve_endpoint(base_url=g.base_url, endpoint_env=g.endpoint_env, engine=g.engine),
        embed=resolve_endpoint(base_url=e.base_url, endpoint_env=e.endpoint_env, engine=e.engine),
    )


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


def build_retriever(cfg: RagConfig, settings: Settings, embed_url: str) -> Retriever:
    """The retriever with the dense encoder of ``cfg.embed.engine``."""
    encoder: DenseEncoder = (
        PendingOllamaEncoder()
        if cfg.embed.engine == "ollama"
        else TeiDenseEncoder(cfg.embed, embed_url)
    )
    return Retriever(
        cfg,
        settings.qdrant_url,
        encoder,
        build_analyzer(cfg),
        SparseEncoder(),
        collection=settings.collection,
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
