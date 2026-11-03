"""``LLMClient``: policy -> cache -> retries/quota -> backend -> recorder -> budget, plus JSON."""

from collections.abc import Callable
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from pruefstand.core.errors import ConfigError, LLMError, PolicyViolation, QuotaExhausted
from pruefstand.core.hashing import stable_hash
from pruefstand.core.models.llm import LLMRequest, LLMResponse
from pruefstand.core.protocols import KVCache, LLMBackend
from pruefstand.llm.budget import Budget
from pruefstand.llm.json_call import (
    Pending,
    complete_json_response,
    repair_max_tokens,
)
from pruefstand.llm.policy import LOCAL_PROVIDERS, LLMPolicy, provider_of
from pruefstand.llm.recorder import CallRecorder
from pruefstand.llm.retry import Retrier, RetryPolicy, describe

__all__ = ["LLMClient", "cache_key", "repair_max_tokens"]  # the last is a re-export (T1.4 API)
T = TypeVar("T", bound=BaseModel)
CACHE_NAMESPACE = "llm"


def cache_key(req: LLMRequest, model_version: str | None = None, epoch: int = 0) -> str:
    """Return the LLM cache key (interfaces §8, namespace ``llm``; round 8 W3.2, D113).

    The key covers the model, the provider-reported version suffixed with the judge's cache epoch
    (``<version>#e<epoch>``), prompt id and version, the rendered messages (question, answer,
    every context chunk and the reference are in them), temperature, max tokens, seed and
    response format, and the JSON schema when the request has one (T5.2a; a request without a
    schema keeps its earlier key). Qwen3's ``enable_thinking=false`` follows from the model
    id (D95).

    Examples:
        >>> from pruefstand.core.models.llm import LLMRole, Message
        >>> msgs = (Message(role="user", content="a"),)
        >>> r = LLMRequest(role=LLMRole.JUDGE, model="github/x", messages=msgs,
        ...                prompt_id="p", prompt_version="v1")
        >>> cache_key(r) == cache_key(r.model_copy()) != cache_key(r.model_copy(update={"seed": 1}))
        True
        >>> cache_key(r, "gpt-x", 0) != cache_key(r, "gpt-x", 1)
        True
        >>> cache_key(r.model_copy(update={"json_schema": {"type": "object"}})) != cache_key(r)
        True
    """
    version = f"{model_version or ''}#e{epoch}"
    parts: list[object] = [
        req.model, version, req.prompt_id, req.prompt_version, req.messages,
        req.temperature, req.max_tokens, req.seed, req.response_format,
    ]  # fmt: skip
    if req.json_schema is not None:
        parts.append(req.json_schema)
    digest = stable_hash(*parts)
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
        self._retrier = Retrier(retry or RetryPolicy(), recorder)
        self._epochs = epochs
        self._versions: dict[str, str] = {}
        self._exhausted: set[str] = set()

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
        return await self._complete(req, None)

    async def complete_deferred(self, req: LLMRequest, pending: Pending) -> LLMResponse:
        """``complete`` with the cache write deferred into ``pending`` (``flush`` writes it)."""
        return await self._complete(req, pending)

    async def _complete(self, req: LLMRequest, pending: Pending | None) -> LLMResponse:
        """``complete``; with ``pending`` the cache write is deferred to the caller."""
        self._check(req)
        try:
            return await self._serve(self._backend, req, pending, fallback=False)
        except QuotaExhausted:
            self._exhausted.add(req.model)
            if self._fallback is None or self._fallback_model is None:
                raise
            fallback_req = req.model_copy(update={"model": self._fallback_model})
            self._check(fallback_req)  # the data guard applies to the fallback provider too
            try:
                return await self._serve(self._fallback, fallback_req, pending, fallback=True)
            except QuotaExhausted:
                self._exhausted.add(fallback_req.model)
                raise

    def _check(self, req: LLMRequest) -> None:
        try:
            self._policy.check(req, provider_of(req.model))
        except ConfigError as err:  # not provider/model
            violation = PolicyViolation(str(err))
            self._recorder.record(req, None, describe(violation))
            raise violation from err
        except PolicyViolation as err:
            self._recorder.record(req, None, describe(err))
            raise

    async def _serve(
        self,
        backend: LLMBackend,
        req: LLMRequest,
        pending: Pending | None,
        *,
        fallback: bool,
    ) -> LLMResponse:
        version = await self._version(backend, req.model)
        # A provider that can be probed but did not tell its version is never cached (a stale
        # entry of another model could be served), neither read nor written.
        probed = provider_of(req.model) in LOCAL_PROVIDERS and hasattr(backend, "resolve_version")
        cacheable = (
            self._cache is not None and req.temperature == 0 and not (probed and version is None)
        )
        key = self._key(req, version)
        cached = self._lookup(key) if cacheable else None
        if cached is not None:
            self._recorder.record(req, cached, None)
            return cached
        if req.model in self._exhausted:
            err = QuotaExhausted(f"{req.model}: quota exhausted earlier in this run", status=429)
            if self._fallback is None or fallback:  # else the fallback's answer row follows
                self._recorder.record(req, None, describe(err))
            raise err
        self._budget.check()  # a caller that swallowed BudgetExceeded cannot keep sending
        resp = await self._retrier.call(backend, req)
        if fallback:
            resp = resp.model_copy(update={"fallback": True})
        if resp.model_version and req.model not in self._versions:
            self._versions[req.model] = resp.model_version
            key = self._key(req, resp.model_version)
        self._recorder.record(req, resp, None)
        if cacheable and self._cache is not None and resp.text.strip():
            if pending is None:
                self._cache.set(key, resp.model_dump_json().encode("utf-8"))
            else:
                pending.append((key, resp))
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

    def flush(self, pending: Pending) -> None:
        """Write the cache entries a ``complete_deferred`` call kept back."""
        if self._cache is not None:
            for key, resp in pending:
                self._cache.set(key, resp.model_dump_json().encode("utf-8"))

    async def complete_json(self, req: LLMRequest, schema: type[T]) -> T:
        """Answer in JSON mode and validate against ``schema`` (see ``complete_json_response``).

        Args:
            req: The request; ``response_format`` is forced to ``"json"``.
            schema: Pydantic model of the expected object.

        Returns:
            The validated object.

        Raises:
            LLMError: Both answers are invalid (message holds a 200-character excerpt).
        """
        return (await complete_json_response(self, req, schema))[0]

    async def complete_json_meta(self, req: LLMRequest, schema: type[T]) -> tuple[T, LLMResponse]:
        """Like ``complete_json``, plus the response the object came from (T5.2a).

        The response tells the caller whether the answer was ``cached`` and whether the fallback
        backend served it (``fallback``).

        Raises:
            LLMError: Both answers are invalid.
        """
        return await complete_json_response(self, req, schema)


def _fallback_model(fallback: LLMBackend | None) -> str | None:
    if fallback is None:
        return None
    model = getattr(fallback, "model_id", None)
    if not isinstance(model, str):
        msg = "the fallback backend must expose model_id (the model it serves)"
        raise ConfigError(msg)
    return model
