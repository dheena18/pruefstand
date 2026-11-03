"""``create_app``: Target HTTP API v1 (``/v1/query``, ``/v1/info``, ``/v1/health``)."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from rag_demo.analysis.fingerprint import check_fingerprint
from rag_demo.catalogue import CatalogueEntry
from rag_demo.config import Settings, load_config
from rag_demo.errors import IndexMismatchError, RagDemoError
from rag_demo.info import build_info, cpu_model
from rag_demo.models import GenOutput, Hit, RagConfig, Stats
from rag_demo.protocols import Generator
from rag_demo.retrieve import Retriever
from rag_demo.schemas import HealthResponse, InfoResponse, QueryRequest, QueryResponse
from rag_demo.wiring import (
    build_catalogue,
    build_generator,
    build_retriever,
    expected_fingerprint,
    info_env,
    resolve_urls,
)

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


class _CorpusMeta:
    """Corpus version and tenants from the collection metadata, read once.

    Only a collection whose analyzer fingerprint matches is accepted; a stale or differently
    analysed index is refused with 503.
    """

    def __init__(self, qdrant_url: str, collection: str, expected: dict[str, Any]) -> None:
        self._url = f"{qdrant_url.rstrip('/')}/collections/{collection}"
        self._expected = expected
        self._value: dict[str, Any] | None = None

    def get(self) -> dict[str, Any]:
        if self._value is None:
            try:
                resp = httpx.get(self._url, timeout=10)
                meta = resp.json()["result"]["config"]["metadata"]
                if resp.status_code != 200 or not {"corpus_version", "tenants"} <= meta.keys():
                    raise KeyError("metadata")  # noqa: EM101, TRY301
            except (httpx.HTTPError, KeyError, TypeError, ValueError):
                raise HTTPException(503, "index unavailable") from None
            try:
                check_fingerprint(meta.get("analyzer"), self._expected)
            except IndexMismatchError as err:
                raise HTTPException(503, str(err)) from None
            self._value = meta
        return self._value


@dataclass(frozen=True)
class _Parts:
    """The collaborators of one app instance."""

    stats: Stats
    retriever: Retriever
    generator: Generator
    corpus: _CorpusMeta
    env: dict[str, str]
    catalogue: dict[str, CatalogueEntry] | None


def _build_parts(cfg: RagConfig, s: Settings) -> _Parts:
    """Wire one instance; a ``gpu`` config is checked here (catalogue, endpoint variables)."""
    stats = Stats()
    urls = resolve_urls(cfg, s)
    catalogue = build_catalogue(cfg, s)
    return _Parts(
        stats=stats,
        retriever=build_retriever(cfg, s, urls.embed, catalogue),
        generator=build_generator(cfg, urls.llm, stats),
        corpus=_CorpusMeta(s.qdrant_url, s.collection, expected_fingerprint(cfg)),
        env=info_env(s),
        catalogue=catalogue,
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
