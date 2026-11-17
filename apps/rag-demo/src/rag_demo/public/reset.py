"""The test-only reset route of the public demo (N5.4, P5.4, UI13-15)."""

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from rag_demo.public.budget import DailyBudget
from rag_demo.public.errors import Rejection
from rag_demo.public.limits import Limiter

LOOPBACK = frozenset({"127.0.0.1", "::1"})


def add_reset(app: FastAPI, limiter: Limiter, budget: DailyBudget) -> None:
    """``POST /v1/_test/reset`` (N5.4): loopback peers only, 409 while a generation runs."""

    async def reset(request: Request) -> Response:
        peer = request.client.host if request.client else None
        if peer not in LOOPBACK:  # X-Forwarded-For is ignored: this is the TCP peer
            raise HTTPException(404)
        if not limiter.reset():
            return JSONResponse(
                Rejection("busy", 2).body(), status_code=409
            )  # a generation is in flight (UI13-15)
        budget.reset()
        return Response(status_code=204)

    app.add_api_route("/v1/_test/reset", reset, methods=["POST"], include_in_schema=False)
