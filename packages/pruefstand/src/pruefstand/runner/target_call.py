"""One case's exchange with the target: cache lookup, endpoint choice, retries, ``CaseRecord``."""

import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal
from uuid import uuid4

import numpy as np
from pydantic import ValidationError

from pruefstand.core.config import RunnerConfig
from pruefstand.core.errors import StoreError
from pruefstand.core.hashing import stable_hash
from pruefstand.core.ids import CaseId, TenantId
from pruefstand.core.logging import get_logger
from pruefstand.core.models.target import CaseRecord, TargetRequest, TargetResponse
from pruefstand.core.models.testcase import TestCase
from pruefstand.core.protocols import KVCache, TargetAdapter
from pruefstand.runner.retry import Attempts, call_with_retry
from pruefstand.runner.routing import Route

_log = get_logger(__name__)
Mode = Literal["answer", "retrieve"]


@dataclass(frozen=True)
class Fetched:
    """The record of one case and whether ``/v1/retrieve`` was missing (fell back to query)."""

    record: CaseRecord
    fallback: bool


class TargetCaller:
    """Calls the target for one case; owns the target-response cache (namespace ``target``).

    Args:
        adapter: The system under test.
        cache: Optional byte cache; entries hold the mode so an answer is never served for a
            retrieve-only case or the other way round.
        cfg: Timeout, retry and backoff settings.
    """

    def __init__(self, adapter: TargetAdapter, cache: KVCache | None, cfg: RunnerConfig) -> None:
        self._adapter = adapter
        self._cache = cache
        self._cfg = cfg

    async def fetch(
        self, case: TestCase, route: Route, *, target_fingerprint: str, rng: np.random.Generator
    ) -> Fetched:
        """Return the record for ``case``: from the cache, else from the target.

        Args:
            case: The test case.
            route: The endpoint family chosen by ``route_case``.
            target_fingerprint: Part of the cache key.
            rng: Seeded generator for the retry jitter.

        Returns:
            The record (``error`` set when the request finally failed) and the fallback flag.
        """
        key = stable_hash(target_fingerprint, case.id, case.question, case.tenant)
        request = TargetRequest(
            tenant_id=TenantId(case.tenant), question=case.question, request_id=uuid4().hex
        )
        hit = self._lookup(key, route.mode)
        if hit is not None:
            response, latency_ms = hit
            hit_result = Attempts(response, None, 0)
            record = _record(case, request, hit_result, latency_ms, route.mode, cached=True)
            return Fetched(record, fallback=False)
        mode, fallback = route.mode, False
        timing = [0.0]
        result = await self._attempt(self._timed(self._call(mode, request), timing), rng)
        if mode == "retrieve" and result.error is None and result.value is None:
            mode, fallback = "answer", True  # target without /v1/retrieve (404/405)
            result = await self._attempt(self._timed(self._call(mode, request), timing), rng)
        record = _record(case, request, result, timing[0], mode, cached=False)
        if record.response is not None:
            self._store(key, record)
        return Fetched(record, fallback=fallback)

    def _call(
        self, mode: Mode, request: TargetRequest
    ) -> Callable[[], Awaitable[TargetResponse | None]]:
        async def query() -> TargetResponse | None:
            return await self._adapter.query(request)

        async def retrieve() -> TargetResponse | None:
            found = await self._adapter.retrieve(request)
            return None if found is None else TargetResponse(answer="", chunks=found.chunks)

        return retrieve if mode == "retrieve" else query

    @staticmethod
    def _timed(
        call: Callable[[], Awaitable[TargetResponse | None]], timing: list[float]
    ) -> Callable[[], Awaitable[TargetResponse | None]]:
        async def timed() -> TargetResponse | None:
            started = time.perf_counter()
            try:
                return await call()
            finally:
                timing[0] = (time.perf_counter() - started) * 1000.0

        return timed

    async def _attempt(
        self, call: Callable[[], Awaitable[TargetResponse | None]], rng: np.random.Generator
    ) -> Attempts[TargetResponse | None]:
        return await call_with_retry(
            call,
            timeout_s=self._cfg.timeout_s,
            max_retries=self._cfg.max_retries,
            backoff_s=self._cfg.backoff_s,
            rng=rng,
        )

    def _lookup(self, key: str, mode: Mode) -> tuple[TargetResponse, float] | None:
        raw = None if self._cache is None else self._cache.get(key)
        if raw is None:
            return None
        try:
            entry = json.loads(raw)
            if entry["mode"] != mode:
                return None
            return TargetResponse.model_validate(entry["response"]), float(entry["latency_ms"])
        except (ValueError, KeyError, TypeError, ValidationError):
            _log.warning("target_cache_entry_unreadable", key=key)
            return None

    def _store(self, key: str, record: CaseRecord) -> None:
        if self._cache is None or record.response is None:
            return
        entry = {
            "mode": record.mode,
            "latency_ms": record.latency_ms,
            "response": record.response.model_dump(mode="json"),
        }
        try:
            self._cache.set(key, json.dumps(entry, ensure_ascii=False).encode("utf-8"))
        except StoreError as exc:
            _log.warning("target_cache_write_failed", error=str(exc))


def _record(
    case: TestCase,
    request: TargetRequest,
    result: Attempts[TargetResponse | None],
    latency_ms: float,
    mode: Mode,
    *,
    cached: bool,
) -> CaseRecord:
    return CaseRecord(
        case_id=CaseId(case.id),
        request=request,
        response=result.value,
        error=result.error,
        latency_ms=latency_ms,
        cached=cached,
        attempt=result.attempts,
        mode=mode,
    )
