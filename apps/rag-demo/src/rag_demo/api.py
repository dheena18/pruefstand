"""``create_app``: Target HTTP API v1 (``/v1/query``, ``/v1/info``, ``/v1/health``)."""

import asyncio
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException

from rag_demo import __version__
from rag_demo.analysis import GermanAnalyzer
from rag_demo.config import Settings, config_hash, load_config
from rag_demo.dense import TeiDenseEncoder
from rag_demo.errors import RagDemoError
from rag_demo.generate import LlamaCppGenerator
from rag_demo.models import GenOutput, Hit, RagConfig, Stats
from rag_demo.retrieve import Retriever
from rag_demo.schemas import HealthResponse, InfoResponse, QueryRequest, QueryResponse
from rag_demo.sparse import SparseEncoder

_log = logging.getLogger(__name__)


def to_query_response(hits: list[Hit], gen: GenOutput, prompt_hits: list[Hit]) -> dict[str, Any]:
    """Map retrieval and generation results to the ``/v1/query`` body (X3.14).

    Every chunk of ``hits`` is returned in rank order; ``used_in_prompt`` is true for those that
    are in ``prompt_hits`` (the chunks the generator prompt actually held).
    """
    used = {h.chunk_id for h in prompt_hits}
    return {
        "answer": gen.answer,
        "citations": gen.citations,
        "chunks": [
            {
                "chunk_id": h.chunk_id,
                "doc_id": h.doc_id,
                "tenant_id": h.tenant_id,
                "text": h.text,
                "score": h.score,
                "rank": h.rank,
                "used_in_prompt": h.chunk_id in used,
            }
            for h in hits
        ],
        "refused": gen.refused,
        "model": gen.model,
        "usage": {"prompt_tokens": gen.prompt_tokens, "completion_tokens": gen.completion_tokens},
    }


def build_health(stats: Stats) -> dict[str, Any]:
    """The ``/v1/health`` body: status and the runtime counters."""
    return {
        "status": "ok",
        "stats": {
            "think_stripped": stats.think_stripped,
            "truncated_chunks": stats.truncated_chunks,
            "requests": stats.requests,
        },
    }


def cpu_model(cpuinfo: Path = Path("/proc/cpuinfo")) -> str:
    """The CPU model name of this host ("unknown" if it cannot be read)."""
    try:
        for line in cpuinfo.read_text(encoding="utf-8").splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return "unknown"


def build_info(
    cfg: RagConfig, *, corpus_version: str, env: Mapping[str, str], cpu_model: str
) -> dict[str, Any]:
    """The ``/v1/info`` body; ``serving`` holds static fields only (X3.13).

    Args:
        cfg: Active configuration.
        corpus_version: From the collection metadata.
        env: ``GIT_SHA``, ``IMAGE_DIGEST``, ``LLAMA_CPP_VERSION``, ``MODEL_SHA256``.
        cpu_model: CPU model name; part of the target fingerprint via ``serving.gpu`` (AI-36).
    """
    return {
        "app_version": __version__,
        "git_sha": env.get("GIT_SHA", "unknown"),
        "image_digest": env.get("IMAGE_DIGEST") or None,
        "config_hash": config_hash(cfg),
        "corpus_version": corpus_version,
        "models": {
            "generator": cfg.generator.model,
            "generator_family": cfg.generator.family,
            "embedding": cfg.embed.model,
        },
        "serving": {
            "engine": "llama.cpp",
            "engine_version": env.get("LLAMA_CPP_VERSION", "unknown"),
            "quantization": "Q4_K_M",
            "gpu": f"cpu:{cpu_model}",
            "model_sha256": env.get("MODEL_SHA256", "unknown"),
        },
    }


class _CorpusMeta:
    """Corpus version and tenant list, read once from the Qdrant collection metadata."""

    def __init__(self, qdrant_url: str, collection: str) -> None:
        self._url = f"{qdrant_url.rstrip('/')}/collections/{collection}"
        self._value: dict[str, Any] | None = None

    def get(self) -> dict[str, Any]:
        if self._value is None:
            try:
                resp = httpx.get(self._url, timeout=10)
                meta = resp.json()["result"]["config"]["metadata"]
                if resp.status_code != 200 or "corpus_version" not in meta:
                    raise KeyError("metadata")  # noqa: EM101, TRY301
            except (httpx.HTTPError, KeyError, TypeError, ValueError):
                raise HTTPException(503, "index unavailable") from None
            self._value = meta
        return self._value


@dataclass(frozen=True)
class _Parts:
    """The collaborators of one app instance."""

    stats: Stats
    retriever: Retriever
    generator: LlamaCppGenerator
    corpus: _CorpusMeta
    env: dict[str, str]


def _build_parts(cfg: RagConfig, s: Settings) -> _Parts:
    stats = Stats()
    retriever = Retriever(
        cfg,
        s.qdrant_url,
        TeiDenseEncoder(cfg.embed, s.embed_url),
        GermanAnalyzer(compound_split=False, stemmer="none"),
        SparseEncoder(),
        collection=s.collection,
    )
    env = {
        "GIT_SHA": s.git_sha,
        "IMAGE_DIGEST": s.image_digest or "",
        "LLAMA_CPP_VERSION": s.llama_cpp_version,
        "MODEL_SHA256": s.model_sha256,
    }
    return _Parts(
        stats=stats,
        retriever=retriever,
        generator=LlamaCppGenerator(cfg, s.llm_url, stats=stats),
        corpus=_CorpusMeta(s.qdrant_url, s.collection),
        env=env,
    )


def _add_routes(app: FastAPI, cfg: RagConfig, parts: _Parts) -> None:
    @app.post("/v1/query", operation_id="query", response_model=QueryResponse)
    async def query(req: QueryRequest) -> dict[str, Any]:
        meta = await asyncio.to_thread(parts.corpus.get)
        if req.tenant_id not in meta["tenants"]:
            raise HTTPException(422, "unknown tenant")
        parts.stats.requests += 1
        try:
            hits = await asyncio.to_thread(
                parts.retriever.retrieve, req.tenant_id, req.question, req.top_k or cfg.top_k
            )
            gen = await parts.generator.answer(req.question, hits)
        except RagDemoError as err:
            _log.warning("query failed: %s", err)
            raise HTTPException(503, "backend unavailable") from None
        prompted = [h for h in hits if h.chunk_id in set(gen.prompt_chunk_ids)]
        return to_query_response(hits, gen, prompted)

    @app.get("/v1/info", operation_id="info", response_model=InfoResponse)
    async def info() -> dict[str, Any]:
        meta = await asyncio.to_thread(parts.corpus.get)
        return build_info(
            cfg, corpus_version=meta["corpus_version"], env=parts.env, cpu_model=cpu_model()
        )

    @app.get("/v1/health", operation_id="health", response_model=HealthResponse)
    async def health() -> dict[str, Any]:
        return build_health(parts.stats)


def create_app(cfg: RagConfig, *, settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI app that implements Target HTTP API v1.

    Args:
        cfg: The RAG configuration (bug switches included).
        settings: Deployment settings; default reads the environment.

    Returns:
        The app. Collaborator clients connect lazily, so building it needs no running service.
    """
    app = FastAPI(title="Prüfstand Target API", version="1")
    _add_routes(app, cfg, _build_parts(cfg, settings or Settings()))
    return app


def create_default_app() -> FastAPI:
    """Factory for ``uvicorn --factory``: the config file comes from ``RAG_CONFIG``."""
    settings = Settings()
    return create_app(load_config(settings.rag_config), settings=settings)
