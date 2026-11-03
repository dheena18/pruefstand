"""``create_app``: Target HTTP API v1 (``/v1/query``, ``/v1/info``, ``/v1/health``)."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from rag_demo.catalogue import CatalogueEntry
from rag_demo.config import Settings, load_config
from rag_demo.errors import (
    IndexMismatchError,
    IndexUnavailableError,
    RagDemoError,
    UnknownTenantError,
)
from rag_demo.generation import prompt_hits
from rag_demo.info import build_info, cpu_model
from rag_demo.models import GenOutput, Hit, RagConfig, Stats
from rag_demo.protocols import Generator
from rag_demo.retrieval.corpus_meta import CorpusMeta
from rag_demo.retrieval.rerank import IdentityReranker
from rag_demo.retrieval.retriever import QdrantRetriever
from rag_demo.schemas import (
    HealthResponse,
    InfoResponse,
    QueryRequest,
    QueryResponse,
    RetrieveResponse,
)
from rag_demo.wiring import (
    build_catalogue,
    build_corpus,
    build_generator,
    build_retriever,
    info_env,
    resolve_urls,
)

_log = logging.getLogger(__name__)


def to_query_response(hits: list[Hit], gen: GenOutput, prompted: list[Hit]) -> dict[str, Any]:
    """Map retrieval and generation results to the ``/v1/query`` body (X3.14).

    The chunks of ``prompted`` come first, in prompt order and with the (truncated) text the
    prompt held, ``used_in_prompt`` true; further retrieved chunks of ``hits`` follow with
    ``used_in_prompt`` false.
    """
    used = {h.chunk_id for h in prompted}
    ordered = [(h, True) for h in prompted] + [(h, False) for h in hits if h.chunk_id not in used]
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
                "used_in_prompt": in_prompt,
            }
            for h, in_prompt in ordered
        ],
        "refused": gen.refused,
        "model": gen.model,
        "usage": {"prompt_tokens": gen.prompt_tokens, "completion_tokens": gen.completion_tokens},
    }


def to_retrieve_response(hits: list[Hit]) -> dict[str, Any]:
    """The ``/v1/retrieve`` body: the chunks of ``to_query_response`` without ``used_in_prompt``."""
    return {
        "chunks": [
            {
                "chunk_id": h.chunk_id,
                "doc_id": h.doc_id,
                "tenant_id": h.tenant_id,
                "text": h.text,
                "score": h.score,
                "rank": h.rank,
            }
            for h in hits
        ]
    }


def build_health(stats: Stats) -> dict[str, Any]:
    """The ``/v1/health`` body: status and the runtime counters."""
    return {
        "status": "ok",
        "stats": {
            "think_stripped": stats.think_stripped,
            "truncated_chunks": stats.truncated_chunks,
            "requests": stats.requests,
            "prompt_overflow": stats.prompt_overflow,
        },
    }


@dataclass(frozen=True)
class _Parts:
    """The collaborators of one app instance."""

    stats: Stats
    retriever: QdrantRetriever
    retrieve_only: QdrantRetriever
    generator: Generator
    corpus: CorpusMeta
    env: dict[str, str]
    catalogue: dict[str, CatalogueEntry] | None


def _build_parts(cfg: RagConfig, s: Settings) -> _Parts:
    """Wire one instance; a ``gpu`` config is checked here (catalogue, endpoint variables)."""
    stats = Stats()
    urls = resolve_urls(cfg, s)
    catalogue = build_catalogue(cfg, s)
    corpus = build_corpus(cfg, s)
    retriever = build_retriever(cfg, s, urls.embed, catalogue, corpus=corpus)
    return _Parts(
        stats=stats,
        retriever=retriever,
        # D271: on_retrieve false = /v1/retrieve skips the reranker (/v1/query never does)
        retrieve_only=retriever
        if cfg.rerank.on_retrieve
        else retriever.with_reranker(IdentityReranker()),
        generator=build_generator(
            cfg, urls.llm, stats, catalogue=catalogue, tokenizer=s.generator_tokenizer
        ),
        corpus=corpus,
        env=info_env(s),
        catalogue=catalogue,
    )


async def _meta(parts: _Parts) -> dict[str, Any]:
    """The checked collection metadata; an unreadable, incomplete or mismatched index is a 503."""
    try:
        return await asyncio.to_thread(parts.corpus.get)
    except (IndexUnavailableError, IndexMismatchError) as err:
        raise HTTPException(503, str(err)) from None


def _http_error(err: RagDemoError, what: str) -> HTTPException:
    """422 for a malformed tenant of the index, else 503 without details."""
    if isinstance(err, UnknownTenantError):
        return HTTPException(422, "unknown tenant")
    _log.warning("%s failed: %s", what, err)
    return HTTPException(503, "backend unavailable")


async def _checked_tenant(parts: _Parts, tenant_id: str) -> None:
    """Refuse an unknown tenant with 422 (after the index check)."""
    if tenant_id not in (await _meta(parts))["tenants"]:
        raise HTTPException(422, "unknown tenant")


def _add_routes(app: FastAPI, cfg: RagConfig, parts: _Parts) -> None:
    @app.post("/v1/query", operation_id="query", response_model=QueryResponse)
    async def query(req: QueryRequest) -> dict[str, Any]:
        await _checked_tenant(parts, req.tenant_id)
        parts.stats.requests += 1
        try:
            hits = await asyncio.to_thread(
                parts.retriever.retrieve, req.tenant_id, req.question, req.top_k or cfg.top_k
            )
            gen = await parts.generator.answer(req.question, hits)
        except RagDemoError as err:
            raise _http_error(err, "query") from None
        by_id = {h.chunk_id: h for h in hits}
        prompted = prompt_hits([by_id[i] for i in gen.prompt_chunk_ids], cfg)
        _log.debug("request_id=%s prompt_chunk_ids=%s", req.request_id, gen.prompt_chunk_ids)
        return to_query_response(hits, gen, prompted)

    @app.post(
        "/v1/retrieve",
        operation_id="retrieve",
        response_model=RetrieveResponse,
        response_model_exclude_unset=True,
    )
    async def retrieve(req: QueryRequest) -> dict[str, Any]:
        """Retrieval only (D218): the chunks `/v1/query` would return, no generator call."""
        await _checked_tenant(parts, req.tenant_id)
        parts.stats.requests += 1
        try:
            hits = await asyncio.to_thread(
                parts.retrieve_only.retrieve, req.tenant_id, req.question, req.top_k or cfg.top_k
            )
        except RagDemoError as err:
            raise _http_error(err, "retrieve") from None
        return to_retrieve_response(hits)

    @app.get("/v1/info", operation_id="info", response_model=InfoResponse)
    async def info() -> dict[str, Any]:
        meta = await _meta(parts)
        return build_info(
            cfg,
            corpus_version=meta["corpus_version"],
            env=parts.env,
            cpu_model=cpu_model(),
            catalogue=parts.catalogue,
        )

    @app.get("/v1/health", operation_id="health", response_model=HealthResponse)
    async def health() -> dict[str, Any]:
        return build_health(parts.stats)


MAX_BODY_BYTES = 16 * 1024


def _add_guards(app: FastAPI) -> None:
    """Body size limit (413) and validation errors that never echo the input (422)."""

    @app.middleware("http")
    async def limit_body(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if int(request.headers.get("content-length") or 0) > MAX_BODY_BYTES:
            return JSONResponse({"detail": "request body too large"}, status_code=413)
        return await call_next(request)

    @app.exception_handler(RequestValidationError)
    async def invalid(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [{"loc": e["loc"], "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
        return JSONResponse({"detail": errors}, status_code=422)


def create_app(cfg: RagConfig, *, settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI app that implements Target HTTP API v1.

    Args:
        cfg: The RAG configuration (bug switches included).
        settings: Deployment settings; default reads the environment.

    Returns:
        The app. Collaborator clients connect lazily, so building it needs no running service.
    """
    app = FastAPI(title="Prüfstand Target API", version="1")
    _add_guards(app)
    _add_routes(app, cfg, _build_parts(cfg, settings or Settings()))
    return app


def create_default_app() -> FastAPI:
    """Factory for ``uvicorn --factory``: the config file comes from ``RAG_CONFIG``."""
    settings = Settings()
    return create_app(load_config(settings.rag_config), settings=settings)
