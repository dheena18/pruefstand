"""``LLMClient``: policy -> cache -> retries/quota -> backend -> recorder -> budget, plus JSON."""

from collections.abc import Callable
from typing import TypeVar

import numpy as np
from pydantic import BaseModel, ValidationError

from pruefstand.core.errors import ConfigError, LLMError, PolicyViolation, QuotaExhausted
from pruefstand.core.hashing import stable_hash
from pruefstand.core.models.llm import LLMRequest, LLMResponse
from pruefstand.core.protocols import KVCache, LLMBackend
from pruefstand.llm import retry as retrying
from pruefstand.llm.budget import Budget
from pruefstand.llm.json_extract import MAX_CANDIDATES, MAX_SCAN_CHARS, extract_json_object
from pruefstand.llm.policy import LOCAL_PROVIDERS, LLMPolicy, provider_of
from pruefstand.llm.prompts import PromptRegistry
from pruefstand.llm.recorder import CallRecorder
from pruefstand.llm.retry import RateLimitedError, RetryPolicy

T = TypeVar("T", bound=BaseModel)
CACHE_NAMESPACE = "llm"
_EXCERPT = 200
MAX_REPAIR_TOKENS = 16384
HTTP_TOO_MANY_REQUESTS = 429


def repair_max_tokens(max_tokens: int) -> int:
    """Return the repair call's token budget: doubled, capped at 16384, never below the original.

    Examples:
        >>> repair_max_tokens(12), repair_max_tokens(9000), repair_max_tokens(20000)
        (24, 16384, 20000)
    """
    return max(max_tokens, min(max_tokens * 2, MAX_REPAIR_TOKENS))


def cache_key(req: LLMRequest, model_version: str | None = None, epoch: int = 0) -> str:
    """Return the LLM cache key (interfaces §8, namespace ``llm``; round 8 W3.2, D113).

    The key covers the model, the provider-reported version suffixed with the judge's cache epoch
    (``<version>#e<epoch>``), prompt id and version, the rendered messages (question, answer,
    every context chunk and the reference are in them), temperature, max tokens, seed and
    response format. Qwen3's ``enable_thinking=false`` follows from the model id (D95).

    Examples:
        >>> from pruefstand.core.models.llm import LLMRole, Message
        >>> msgs = (Message(role="user", content="a"),)
        >>> r = LLMRequest(role=LLMRole.JUDGE, model="github/x", messages=msgs,
        ...                prompt_id="p", prompt_version="v1")
        >>> cache_key(r) == cache_key(r.model_copy()) != cache_key(r.model_copy(update={"seed": 1}))
        True
        >>> cache_key(r, "gpt-x", 0) != cache_key(r, "gpt-x", 1)
        True
    """
    version = f"{model_version or ''}#e{epoch}"
    digest = stable_hash(
        req.model, version, req.prompt_id, req.prompt_version, req.messages,
        req.temperature, req.max_tokens, req.seed, req.response_format,
    )  # fmt: skip
    return f"{CACHE_NAMESPACE}:{digest}"


class LLMClient:
    """The only door to a model: policy, cache, retries, budget and call log around one backend.

    Args:
        backend: The real backend.
        cache: Optional byte cache (in-memory dict in tests, ``DiskKVCache`` in production).
            Only ``temperature == 0`` requests are cached.
        budget: Run budget; charged once per real call, never for cache hits.
        recorder: Receives one row per attempt, hit or failure.
        policy: Provider policy, checked before every call (also for the fallback).
        fallback: Backend that serves a model after its provider's quota is exhausted; it must
            expose ``model_id`` (``LiteLLMBackend`` does). Answers carry ``fallback=True``.
        retry: Backoff policy (T5.1 addition, keyword only).
        epochs: Cache epoch of a model id (``cache_epochs.current_epoch``), part of the cache key
            (T5.1 addition, keyword only; None = epoch 0).

    Raises:
        ConfigError: ``fallback`` has no ``model_id``.
    """

    def __init__(
        self,
        backend: LLMBackend,
        cache: KVCache | None,
        budget: Budget,
        recorder: CallRecorder,
        policy: LLMPolicy,
        *,
        fallback: LLMBackend | None = None,
        retry: RetryPolicy | None = None,
        epochs: Callable[[str], int] | None = None,
    ) -> None:
        self._backend = backend
        self._cache = cache
        self._budget = budget
        self._recorder = recorder
        self._policy = policy
        self._fallback = fallback
        self._fallback_model = _fallback_model(fallback)
        self._retry = retry or RetryPolicy()
        self._rng = np.random.default_rng(self._retry.seed)
        self._epochs = epochs
        self._versions: dict[str, str] = {}
        self._exhausted: set[str] = set()
        self._prompts = PromptRegistry()

    async def complete(self, req: LLMRequest) -> LLMResponse:
        """Answer ``req`` from the cache or the backend.

        Args:
            req: The request.

        Returns:
            The response; ``cached=True`` for a hit (not charged to the budget);
            ``fallback=True`` when the fallback backend answered.

        Raises:
            PolicyViolation: The provider policy refuses the request (no call is made).
            QuotaExhausted: The provider's free quota is used up and there is no fallback; later
                calls to that model fail at once, without a network call.
            LLMError: The backend failed after the retries (cause chained).
            BudgetExceeded: The answered call pushed the budget over a limit.
        """
        self._check(req)
        try:
            return await self._serve(self._backend, req, fallback=False)
        except QuotaExhausted:
            self._exhausted.add(req.model)
            if self._fallback is None or self._fallback_model is None:
                raise
            fallback_req = req.model_copy(update={"model": self._fallback_model})
            self._check(fallback_req)  # the data guard applies to the fallback provider too
            return await self._serve(self._fallback, fallback_req, fallback=True)

    def _check(self, req: LLMRequest) -> None:
        try:
            self._policy.check(req, provider_of(req.model))
        except ConfigError as err:  # not provider/model
            violation = PolicyViolation(str(err))
            self._recorder.record(req, None, _describe(violation))
            raise violation from err
        except PolicyViolation as err:
            self._recorder.record(req, None, _describe(err))
            raise

    async def _serve(self, backend: LLMBackend, req: LLMRequest, *, fallback: bool) -> LLMResponse:
        version = await self._version(backend, req.model)
        key = self._key(req, version)
        cached = self._lookup(key)
        if cached is not None:
            self._recorder.record(req, cached, None)
            return cached
        if req.model in self._exhausted and not fallback:
            err = QuotaExhausted(f"{req.model}: quota exhausted earlier in this run", status=429)
            if self._fallback is None:  # with a fallback the answer row follows at once
                self._recorder.record(req, None, _describe(err))
            raise err
        self._budget.check()  # a caller that swallowed BudgetExceeded cannot keep sending
        resp = await self._call(backend, req)
        if fallback:
            resp = resp.model_copy(update={"fallback": True})
        if resp.model_version and req.model not in self._versions:
            self._versions[req.model] = resp.model_version
            key = self._key(req, resp.model_version)
        self._recorder.record(req, resp, None)
        if self._cache is not None and req.temperature == 0:
            self._cache.set(key, resp.model_dump_json().encode("utf-8"))
        self._budget.charge(resp)
        return resp

    def _key(self, req: LLMRequest, version: str | None) -> str:
        epoch = self._epochs(req.model) if self._epochs is not None else 0
        return cache_key(req, version, epoch)

    async def _version(self, backend: LLMBackend, model: str) -> str | None:
        """Resolve the provider-reported version once per model and run (D113)."""
        if model in self._versions:
            return self._versions[model]
        probe = getattr(backend, "resolve_version", None)
        if probe is None:
            return None
        try:
            version = await probe(model)
        except LLMError:
            return None  # the real call that follows reports the outage
        if isinstance(version, str):
            self._versions[model] = version
            return version
        return None

    def _lookup(self, key: str) -> LLMResponse | None:
        """Return the cached response, or None on a miss or an unreadable entry."""
        hit = self._cache.get(key) if self._cache is not None else None
        if hit is None:
            return None
        try:
            return LLMResponse.model_validate_json(hit).model_copy(update={"cached": True})
        except ValidationError:
            return None  # a corrupt entry is a miss; the fresh answer overwrites it

    async def _call(self, backend: LLMBackend, req: LLMRequest) -> LLMResponse:
        """One logical call: retry transient failures; every failed attempt is recorded."""
        for attempt in range(self._retry.max_retries + 1):
            try:
                return await backend.acomplete(req)
            except LLMError as err:
                await self._after_failure(req, err, attempt)  # raises unless a retry follows
            except Exception as err:
                self._recorder.record(req, None, type(err).__name__)  # no message: may hold secrets
                msg = f"backend failed: {type(err).__name__}"
                raise LLMError(msg, transient=False) from err
        msg = "retry loop ended without an answer"  # unreachable: the last attempt raises
        raise LLMError(msg, transient=False)

    async def _after_failure(self, req: LLMRequest, err: LLMError, attempt: int) -> None:
        """Decide after a failed attempt: raise (permanent, last, quota) or sleep and return."""
        policy = self._retry
        wait = err.retry_after_s if isinstance(err, RateLimitedError) else None
        final = attempt >= policy.max_retries
        external_429 = err.status == HTTP_TOO_MANY_REQUESTS and (
            provider_of(req.model) not in LOCAL_PROVIDERS
        )
        if external_429 and (final or (wait is not None and wait > policy.max_retry_after_s)):
            self._recorder.record(req, None, _describe(err))
            msg = f"{req.model}: free quota exhausted ({_describe(err)})"
            raise QuotaExhausted(msg, status=HTTP_TOO_MANY_REQUESTS) from err
        if not external_429 and (not err.transient or final):
            self._recorder.record(req, None, _describe(err))
            raise err
        self._recorder.record(req, None, f"retry {attempt + 1}: {_describe(err)}")
        await retrying.pause(retrying.backoff_delay(policy, attempt, wait, self._rng))

    async def complete_json(self, req: LLMRequest, schema: type[T]) -> T:
        """Answer in JSON mode and validate against ``schema``.

        The first JSON object of the text is extracted (code fences stripped). On failure one
        repair call follows: the request plus ``json_repair_v1`` and **doubled** ``max_tokens``
        (truncation is the usual cause).

        Args:
            req: The request; ``response_format`` is forced to ``"json"``.
            schema: Pydantic model of the expected object.

        Returns:
            The validated object.

        Raises:
            LLMError: Both answers are invalid (message holds a 200-character excerpt).
        """
        first = req.model_copy(update={"response_format": "json"})
        resp = await self.complete(first)
        parsed = _parse(resp.text, schema)
        if parsed is not None:
            return parsed
        repair = self._prompts.get("json_repair", "v1").render()
        again = first.model_copy(
            update={
                "messages": (*first.messages, *repair),
                "max_tokens": repair_max_tokens(first.max_tokens),
            }
        )
        resp = await self.complete(again)
        parsed = _parse(resp.text, schema)
        if parsed is None:
            msg = (
                "invalid JSON after one repair "
                f"(only the first {MAX_SCAN_CHARS // 1024} KiB are scanned, at most "
                f"{MAX_CANDIDATES} candidates tried): {resp.text[:_EXCERPT]!r}"
            )
            raise LLMError(msg, transient=False)
        return parsed


def _fallback_model(fallback: LLMBackend | None) -> str | None:
    if fallback is None:
        return None
    model = getattr(fallback, "model_id", None)
    if not isinstance(model, str):
        msg = "the fallback backend must expose model_id (the model it serves)"
        raise ConfigError(msg)
    return model


def _parse[M: BaseModel](text: str, schema: type[M]) -> M | None:
    raw = extract_json_object(text)
    if raw is None:
        return None
    try:
        return schema.model_validate_json(raw)
    except ValidationError:
        return None


def _describe(err: Exception) -> str:
    return f"{type(err).__name__}: {err}"[: _EXCERPT * 2]
