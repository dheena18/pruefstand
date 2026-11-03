"""Calls the rewrite model; falls back to the local model when the data guard blocks (ADR-0019)."""

import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from pruefstand.core.errors import DataGuardViolation
from pruefstand.core.models.llm import LLMRequest, LLMRole, Message
from pruefstand.core.protocols import LLMClientLike
from pruefstand.llm.policy import PRIVATE_PROMPT_PREFIX
from pruefstand.llm.prompts import PromptRegistry

PROMPT_VERSION = "v1"
MAX_TOKENS = 256
PROMPTS = PromptRegistry(roots=(Path(__file__).resolve().parent / "prompts",))

PUBLIC_TENANT = "shared_public"
_PRIVATE: ContextVar[bool] = ContextVar("perturb_private_text", default=False)
_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)
_LABEL = re.compile(
    r"^(?:umformulierte\s+frage|umformulierung|frage|antwort)\s*:\s*", re.IGNORECASE
)
_QUOTES = "\"'„“”‚‘’«»"


def clean_rewrite(raw: str) -> str:
    """Return the first line of a model answer without label, quotes or ``<think>`` block.

    Examples:
        >>> clean_rewrite('Umformulierte Frage: "Wann darf er?"')
        'Wann darf er?'
        >>> clean_rewrite("   ")
        ''
    """
    text = _THINK.sub("", raw).strip()
    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    return _LABEL.sub("", first).strip().strip(_QUOTES).strip()


@contextmanager
def private_text(*, private: bool) -> Iterator[None]:
    """Mark the model calls inside as carrying private (non-public-tenant) text.

    Their prompt ids start with ``datagen.private_docs`` so the ``LLMPolicy`` data guard refuses
    every external provider, with or without a canary registry. Only the local model answers.
    """
    token = _PRIVATE.set(private)
    try:
        yield
    finally:
        _PRIVATE.reset(token)


def request_prompt_id(prompt_id: str) -> str:
    """Return the request prompt id: ``datagen.private_docs.``-prefixed inside ``private_text``."""
    return f"{PRIVATE_PROMPT_PREFIX}.{prompt_id}" if _PRIVATE.get() else prompt_id


@dataclass(frozen=True)
class LocalTarget:
    """The local model that rewrites what the external provider must not see."""

    llm: LLMClientLike
    model: str


class Rewritten(BaseModel):
    """A cleaned model answer with the model that wrote it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    model: str
    local: bool


class Rewriter:
    """Rewrites a text with a versioned prompt.

    Args:
        model: The rewrite model (``github/<model>`` for public questions).
        local: Local model used when the external call is refused by the data guard.
    """

    def __init__(self, model: str, local: LocalTarget | None = None) -> None:
        self.model = model
        self._local = local

    async def rewrite(self, llm: LLMClientLike, prompt_id: str, **variables: str) -> Rewritten:
        """Rewrite once.

        Args:
            llm: Client of ``self.model``.
            prompt_id: ``<name>_de`` (file ``perturb/prompts/<name>_de_v1.txt``).
            **variables: Prompt variables.

        Returns:
            The cleaned answer (possibly empty) and the model that wrote it.

        Raises:
            DataGuardViolation: The data guard blocked the external call and no local model is set.
            LLMError: The call failed; ``QuotaExhausted`` when the free quota is used up.
            PromptError: Missing prompt file or variables.
        """
        messages = PROMPTS.get(prompt_id, PROMPT_VERSION).render(**variables)
        try:
            external = self._request(LLMRole.PERTURB, self.model, prompt_id, messages)
            resp = await llm.complete(external)
        except DataGuardViolation:
            if self._local is None:
                raise
            local = self._request(LLMRole.DATAGEN, self._local.model, prompt_id, messages)
            resp = await self._local.llm.complete(local)
            return Rewritten(text=clean_rewrite(resp.text), model=self._local.model, local=True)
        return Rewritten(text=clean_rewrite(resp.text), model=self.model, local=False)

    @staticmethod
    def _request(
        role: LLMRole, model: str, prompt_id: str, messages: tuple[Message, ...]
    ) -> LLMRequest:
        return LLMRequest(
            role=role,
            model=model,
            messages=messages,
            temperature=0.0,
            max_tokens=MAX_TOKENS,
            seed=0,
            prompt_id=request_prompt_id(prompt_id),
            prompt_version=PROMPT_VERSION,
        )
