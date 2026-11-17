"""Install public mode on an app: guard, CORS, error bodies and the test-only reset (T8.4)."""

import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from rag_demo.config import Settings
from rag_demo.models import PublicLimits, RagConfig
from rag_demo.public.budget import DailyBudget
from rag_demo.public.errors import Code, Rejection
from rag_demo.public.killswitch import DEFAULT_FLAG, demo_disabled
from rag_demo.public.limits import Limiter
from rag_demo.public.middleware import GuardConfig, PublicGuard

TENANTS = frozenset({"kanzlei_mueller", "versicherung_nord", "stadtwerke_sued"})
LOOPBACK = frozenset({"127.0.0.1", "::1"})
GENERATOR_TIMEOUT = "generator_timeout"


def effective_limits(cfg: RagConfig, settings: Settings) -> PublicLimits:
    """The ``public`` block of the config with the ``DEMO_*`` environment overrides applied."""
    base = cfg.public or PublicLimits()
    overrides = {
        "rate_per_min": settings.demo_rate_per_min,
        "daily_per_key": settings.demo_daily_per_key,
        "daily_requests": settings.demo_daily_requests,
        "daily_tokens": settings.demo_daily_tokens,
        "max_concurrency": settings.demo_max_concurrency,
        "timeout_s": settings.demo_timeout_s,
    }
    return base.model_copy(update={k: v for k, v in overrides.items() if v is not None})


def _error_response(rejection: Rejection, status: int | None = None) -> JSONResponse:
    return JSONResponse(
        rejection.body(), status_code=status or rejection.status, headers=rejection.headers()
    )


def _http_rejection(exc: StarletteHTTPException) -> Rejection:
    """Map any error the app raised to the fixed public codes."""
    detail: object = exc.detail
    if isinstance(detail, dict) and detail.get("code") == GENERATOR_TIMEOUT:
        return Rejection("timeout")
    code: Code
    if exc.status_code == 413:
        code = "body_too_large"
    elif exc.status_code in (404, 405, 422):
        code = "invalid_request"
    else:
        code = "server_error"
    return Rejection(code)


def install_public(app: FastAPI, cfg: RagConfig, settings: Settings) -> None:
    """Add the controls of public mode to ``app`` (call once, after the routes exist)."""
    limits = effective_limits(cfg, settings)
    limiter = Limiter(
        per_min=limits.rate_per_min,
        per_key_day=limits.daily_per_key,
        global_day=limits.daily_requests,
        max_concurrency=limits.max_concurrency,
    )
    budget = DailyBudget(tokens=limits.daily_tokens, requests=limits.daily_requests)
    guard = GuardConfig(
        tenants=TENANTS,
        hops=settings.trusted_proxy_hops,
        max_tokens=cfg.max_tokens,
        timeout_s=limits.timeout_s,
        top_k=cfg.top_k,
    )
    flag = Path(settings.demo_flag_file) if settings.demo_flag_file else DEFAULT_FLAG
    app.add_middleware(
        PublicGuard,
        limiter=limiter,
        budget=budget,
        cfg=guard,
        disabled=lambda: demo_disabled(flag=flag),
        new_id=lambda: uuid.uuid4().hex,
    )
    origin = settings.demo_allowed_origin or limits.allowed_origin
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[origin] if origin else [],
        allow_methods=["POST", "GET"],
        allow_headers=["content-type"],
        expose_headers=["Retry-After"],
    )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        keep = (
            exc.status_code if exc.status_code in (404, 405) else None
        )  # a missing route stays 404
        return _error_response(_http_rejection(exc), keep)

    @app.exception_handler(RequestValidationError)
    async def invalid(_: Request, __: RequestValidationError) -> JSONResponse:
        return _error_response(Rejection("invalid_request"))

    if settings.demo_test_reset == "1":
        _add_reset(app, limiter, budget)


def _add_reset(app: FastAPI, limiter: Limiter, budget: DailyBudget) -> None:
    """``POST /v1/_test/reset`` (N5.4): loopback peers only, 409 while a generation runs."""

    async def reset(request: Request) -> Response:
        peer = request.client.host if request.client else None
        if peer not in LOOPBACK:  # X-Forwarded-For is ignored: this is the TCP peer
            raise HTTPException(404)
        if not limiter.reset():
            return _error_response(Rejection("busy", 2), 409)  # a generation is in flight (UI13-15)
        budget.reset()
        return Response(status_code=204)

    app.add_api_route("/v1/_test/reset", reset, methods=["POST"], include_in_schema=False)
