"""One case's exchange with the target: cache lookup, endpoint choice, retries, ``CaseRecord``."""

import asyncio
import json
import math
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal
from uuid import uuid4

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

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


class _CacheEntry(BaseModel):
    """One cached exchange; finite, non-negative latency only."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: Mode
    latency_ms: float = Field(ge=0, le=86_400_000.0, allow_inf_nan=False)
    response: TargetResponse


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
        self._cache_failed = False

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
        hit = await self._lookup(key, route.mode)
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
        record = _record(
            case, request, _require_valid_unicode(result), timing[0], mode, cached=False
        )
        if record.response is not None:
            await self._store(key, record)
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

    async def _lookup(self, key: str, mode: Mode) -> tuple[TargetResponse, float] | None:
        """Return a cached ``(response, latency_ms)`` or None; every failure is a miss.

        The blob is untrusted (a planted row): it is parsed by one typed model in one step, and
        any failure to parse or validate it, whatever the exception, is a miss.
        """
        if self._cache is None or self._cache_failed:
            return None
        try:
            raw = await asyncio.to_thread(self._cache.get, key)
        except StoreError as exc:
            self._disable_cache("target_cache_read_failed", str(exc))
            return None
        if raw is None:
            return None
        try:
            entry = _CacheEntry.model_validate_json(raw)
        except Exception:
            _log.warning("target_cache_entry_unreadable", key=key)
            return None
        checked = _require_valid_unicode(Attempts(entry.response, None, 0))
        if entry.mode != mode or checked.value is None or not _scores_finite(entry.response):
            return None
        return entry.response, entry.latency_ms

    async def _store(self, key: str, record: CaseRecord) -> None:
        if self._cache is None or self._cache_failed or record.response is None:
            return
        entry = {
            "mode": record.mode,
            "latency_ms": record.latency_ms,
            "response": record.response.model_dump(mode="json"),
        }
        payload = json.dumps(entry, ensure_ascii=False).encode("utf-8")  # valid unicode is checked
        try:
            await asyncio.to_thread(self._cache.set, key, payload)
        except StoreError as exc:
            self._disable_cache("target_cache_write_failed", str(exc))

    def _disable_cache(self, event: str, error: str) -> None:
        """Skip the cache for the rest of the run after its first failure (locked, read-only)."""
        self._cache_failed = True
        _log.warning(event, error=error, note="cache skipped for the rest of the run")


def _scores_finite(response: TargetResponse) -> bool:
    """Same rule as the adapters' wire check: every chunk score is a finite number."""
    return all(math.isfinite(chunk.score) for chunk in response.chunks or ())


def _require_valid_unicode(
    result: Attempts[TargetResponse | None],
) -> Attempts[TargetResponse | None]:
    """Turn a response with lone surrogates into a target error (it cannot be stored or written)."""
    if result.value is None:
        return result
    try:
        result.value.model_dump_json().encode("utf-8")
    except ValueError:
        return Attempts(
            None, "target response is not valid unicode (lone surrogate)", result.attempts
        )
    return result


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
