"""JSON-mode calls: first-object extraction, validation and one repair call (``LLMClient``)."""

from typing import Protocol

from pydantic import BaseModel, ValidationError

from pruefstand.core.errors import LLMError
from pruefstand.core.models.llm import LLMRequest, LLMResponse
from pruefstand.llm.json_extract import MAX_CANDIDATES, MAX_SCAN_CHARS, extract_json_object
from pruefstand.llm.prompts import PromptRegistry

Pending = list[tuple[str, LLMResponse]]
_EXCERPT = 200
MAX_REPAIR_TOKENS = 16384
_PROMPTS = PromptRegistry()


class DeferredClient(Protocol):
    """The part of ``LLMClient`` the JSON call needs: answers whose cache write is deferred."""

    async def complete_deferred(self, req: LLMRequest, pending: Pending) -> LLMResponse:
        """Answer ``req``; cache writes are appended to ``pending`` instead of being made."""
        ...

    def flush(self, pending: Pending) -> None:
        """Write the deferred cache entries."""
        ...


def repair_max_tokens(max_tokens: int) -> int:
    """Return the repair call's token budget: doubled, capped at 16384, never below the original.

    Examples:
        >>> repair_max_tokens(12), repair_max_tokens(9000), repair_max_tokens(20000)
        (24, 16384, 20000)
    """
    return max(max_tokens, min(max_tokens * 2, MAX_REPAIR_TOKENS))


async def complete_json_response[T: BaseModel](
    client: DeferredClient, req: LLMRequest, schema: type[T]
) -> tuple[T, LLMResponse]:
    """Answer in JSON mode, validate against ``schema`` and return the answer's response too.

    The first JSON object of the text is extracted (code fences stripped). On failure one repair
    call follows: the request plus ``json_repair_v1`` and **doubled** ``max_tokens`` (truncation
    is the usual cause). An invalid first answer is never cached.

    Args:
        client: The ``LLMClient``.
        req: The request; ``response_format`` is forced to ``"json"``.
        schema: Pydantic model of the expected object.

    Returns:
        The validated object and the response it was parsed from (``cached``, ``fallback``).

    Raises:
        LLMError: Both answers are invalid (message holds a 200-character excerpt).
    """
    first = req.model_copy(update={"response_format": "json"})
    pending: Pending = []
    resp = await client.complete_deferred(first, pending)
    parsed = _parse(resp.text, schema)
    if parsed is not None:
        client.flush(pending)
        return parsed, resp
    invalid = len(pending)  # entries before this index belong to the invalid first answer
    repair = _PROMPTS.get("json_repair", "v1").render()
    again = first.model_copy(
        update={
            "messages": (*first.messages, *repair),
            "max_tokens": repair_max_tokens(first.max_tokens),
        }
    )
    resp = await client.complete_deferred(again, pending)
    parsed = _parse(resp.text, schema)
    if parsed is None:
        msg = (
            "invalid JSON after one repair "
            f"(only the first {MAX_SCAN_CHARS // 1024} KiB are scanned, at most "
            f"{MAX_CANDIDATES} candidates tried): {resp.text[:_EXCERPT]!r}"
        )
        raise LLMError(msg, transient=False)
    client.flush(pending[invalid:])  # the invalid first answer is never cached
    return parsed, resp


def _parse[M: BaseModel](text: str, schema: type[M]) -> M | None:
    raw = extract_json_object(text)
    if raw is None:
        return None
    try:
        return schema.model_validate_json(raw)
    except ValidationError:
        return None
