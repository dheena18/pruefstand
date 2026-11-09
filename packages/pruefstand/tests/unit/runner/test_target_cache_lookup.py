"""``TargetCaller._lookup`` pinned directly (T1.8a): what is a miss, whatever the cause."""

import json
from typing import Any

import pytest
from testsupport.runner_support import DictCache, new_adapter

from pruefstand.core.config import RunnerConfig
from pruefstand.core.models.target import TargetResponse
from pruefstand.runner.target_call import TargetCaller, _CacheEntry

KEY = "k"
GOOD = {"answer": "Ein Monat.", "citations": []}


def entry_bytes(**changes: Any) -> bytes:
    body = {"mode": "answer", "latency_ms": 12.5, "response": GOOD, **changes}
    return json.dumps(body, ensure_ascii=False).encode("utf-8")


def caller_with(raw: bytes) -> TargetCaller:
    cache = DictCache()
    cache.set(KEY, raw)
    return TargetCaller(new_adapter(), cache, RunnerConfig())


async def test_a_valid_entry_is_a_hit() -> None:
    hit = await caller_with(entry_bytes())._lookup(KEY, "answer")
    assert hit is not None
    assert hit[0].answer == "Ein Monat."
    assert hit[1] == 12.5


@pytest.mark.parametrize("latency", ["NaN", "Infinity", "1e999", "-1", "86400001"])
async def test_a_bad_latency_with_a_valid_response_is_a_miss(latency: str) -> None:
    raw = '{"mode":"answer","latency_ms":' + latency + ',"response":{"answer":"x","citations":[]}}'
    assert await caller_with(raw.encode())._lookup(KEY, "answer") is None


async def test_any_exception_while_parsing_the_blob_is_a_miss_not_only_value_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The blob is untrusted: a parser failure of any type (here a RecursionError) is a miss."""

    def explode(data: object, **kwargs: object) -> _CacheEntry:
        raise RecursionError

    monkeypatch.setattr(_CacheEntry, "model_validate_json", explode)
    assert await caller_with(entry_bytes())._lookup(KEY, "answer") is None


async def test_a_lone_surrogate_that_reaches_a_hit_is_a_miss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Defence in depth: should the parser ever let a lone surrogate through, it is a miss."""
    bad = _CacheEntry.model_construct(
        mode="answer",
        latency_ms=1.0,
        response=TargetResponse.model_construct(answer="x\ud800y", citations=(), chunks=None),
    )
    monkeypatch.setattr(_CacheEntry, "model_validate_json", lambda data, **kwargs: bad)
    assert await caller_with(entry_bytes())._lookup(KEY, "answer") is None
