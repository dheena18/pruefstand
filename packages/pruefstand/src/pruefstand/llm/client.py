"""``LLMClient``: policy -> cache -> backend -> recorder -> budget, plus JSON completion."""

from typing import TypeVar

from pydantic import BaseModel, ValidationError

from pruefstand.core.errors import ConfigError, LLMError, PolicyViolation
from pruefstand.core.hashing import stable_hash
from pruefstand.core.models.llm import LLMRequest, LLMResponse
from pruefstand.core.protocols import KVCache, LLMBackend
from pruefstand.llm.budget import Budget
from pruefstand.llm.json_extract import MAX_CANDIDATES, MAX_SCAN_CHARS, extract_json_object
from pruefstand.llm.policy import LLMPolicy, provider_of
from pruefstand.llm.prompts import PromptRegistry
from pruefstand.llm.recorder import CallRecorder

T = TypeVar("T", bound=BaseModel)
CACHE_NAMESPACE = "llm"
_EXCERPT = 200
MAX_REPAIR_TOKENS = 16384


def repair_max_tokens(max_tokens: int) -> int:
    """Return the repair call's token budget: doubled, capped at 16384, never below the original.

    Examples:
        >>> repair_max_tokens(12), repair_max_tokens(9000), repair_max_tokens(20000)
        (24, 16384, 20000)
    """
    return max(max_tokens, min(max_tokens * 2, MAX_REPAIR_TOKENS))


def cache_key(req: LLMRequest) -> str:
    """Return the LLM cache key (interfaces §8, namespace ``llm``).

    The key covers model, prompt id and version, the rendered messages, temperature, max tokens,
    seed and response format; Qwen3's ``enable_thinking=false`` is derived from the model id, so
    it is part of the key through ``model`` (D95). ``model_version`` joins in T5.1 (D113).

    Examples:
        >>> from pruefstand.core.models.llm import LLMRole, Message
        >>> msgs = (Message(role="user", content="a"),)
        >>> r = LLMRequest(role=LLMRole.JUDGE, model="github/x", messages=msgs,
        ...                prompt_id="p", prompt_version="v1")
        >>> cache_key(r) == cache_key(r.model_copy()) != cache_key(r.model_copy(update={"seed": 1}))
        True
    """
    digest = stable_hash(
        req.model, req.prompt_id, req.prompt_version, req.messages,
        req.temperature, req.max_tokens, req.seed, req.response_format,
    )  # fmt: skip
    return f"{CACHE_NAMESPACE}:{digest}"


class LLMClient:
    """The only door to a model: policy, cache, budget and call log around one backend.

    Args:
        backend: The real backend.
        cache: Optional byte cache (in-memory dict in tests, ``DiskKVCache`` in production).
        budget: Run budget; charged once per real call, never for cache hits.
        recorder: Receives one row per call, hit or failure.
        policy: Provider policy, checked before every call.
        fallback: Tier-2 fallback backend; wired in T5.1.
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
    ) -> None:
        self._backend = backend
        self._cache = cache
        self._budget = budget
        self._recorder = recorder
        self._policy = policy
        self._fallback = fallback
        self._prompts = PromptRegistry()

    async def complete(self, req: LLMRequest) -> LLMResponse:
        """Answer ``req`` from the cache or the backend.

        Args:
            req: The request.

        Returns:
            The response; ``cached=True`` for a hit (not charged to the budget).

        Raises:
            PolicyViolation: The provider policy refuses the request (no call is made).
            LLMError: The backend failed (cause chained).
            BudgetExceeded: The answered call pushed the budget over a limit.
        """
        try:
            self._policy.check(req, provider_of(req.model))
        except ConfigError as err:  # not provider/model
            violation = PolicyViolation(str(err))
            self._recorder.record(req, None, _describe(violation))
            raise violation from err
        except PolicyViolation as err:
            self._recorder.record(req, None, _describe(err))
            raise
        key = cache_key(req)
        cached = self._lookup(key)
        if cached is not None:
            self._recorder.record(req, cached, None)
            return cached
        self._budget.check()  # a caller that swallowed BudgetExceeded cannot keep sending
        resp = await self._call(req)
        self._recorder.record(req, resp, None)
        if self._cache is not None:
            self._cache.set(key, resp.model_dump_json().encode("utf-8"))
        self._budget.charge(resp)
        return resp

    def _lookup(self, key: str) -> LLMResponse | None:
        """Return the cached response, or None on a miss or an unreadable entry."""
        hit = self._cache.get(key) if self._cache is not None else None
        if hit is None:
            return None
        try:
            return LLMResponse.model_validate_json(hit).model_copy(update={"cached": True})
        except ValidationError:
            return None  # a corrupt entry is a miss; the fresh answer overwrites it

    async def _call(self, req: LLMRequest) -> LLMResponse:
        try:
            return await self._backend.acomplete(req)
        except LLMError as err:
            self._recorder.record(req, None, _describe(err))
            raise
        except Exception as err:
            self._recorder.record(req, None, type(err).__name__)  # no message: it may hold secrets
            msg = f"backend failed: {type(err).__name__}"
            raise LLMError(msg, transient=False) from err

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
