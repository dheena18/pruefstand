"""Models of one LLM exchange and of a versioned prompt (interfaces §3)."""

import re
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SerializerFunctionWrapHandler, model_serializer

from pruefstand.core.errors import PromptError
from pruefstand.core.models.target import Usage

PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


class LLMRole(StrEnum):
    """Why a model is called; part of the call record."""

    GENERATOR = "generator"
    JUDGE = "judge"
    DATAGEN = "datagen"
    PERTURB = "perturb"


class Message(BaseModel):
    """One chat message."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    role: Literal["system", "user", "assistant"]
    content: str


class LLMRequest(BaseModel):
    """One model call; every field is part of the cache key.

    ``model`` is the provider-qualified id (``openai_compatible_local/<m>``, ``ollama/<tag>``,
    ``github/<m>``). ``response_format="json"`` asks the provider for JSON mode.
    ``json_schema`` (T5.2a) is a JSON Schema the answer must follow: Ollama gets it as the native
    ``format`` (grammar-constrained decoding), other providers stay in plain JSON mode. It is part
    of the cache key.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    role: LLMRole
    model: str
    messages: tuple[Message, ...]
    temperature: float = 0.0
    max_tokens: int = Field(default=1024, ge=1, le=65536)
    seed: int | None = 0
    prompt_id: str
    prompt_version: str
    response_format: Literal["text", "json"] = "text"
    json_schema: dict[str, object] | None = None

    @model_serializer(mode="wrap")
    def _without_empty_schema(self, handler: SerializerFunctionWrapHandler) -> dict[str, object]:
        """Leave ``json_schema`` out when unset, so earlier cassette hashes and files stay valid."""
        data: dict[str, object] = handler(self)
        if data.get("json_schema") is None:
            data.pop("json_schema", None)
        return data


class LLMResponse(BaseModel):
    """The answer of one model call.

    ``model_version`` is the provider-reported version of the served model (GitHub Models
    ``model`` field); ``fallback`` marks an answer of the tier-2 fallback judge.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    model: str
    usage: Usage
    cost_usd: float
    latency_ms: float
    cached: bool
    provider: str = ""
    fallback: bool = False
    model_version: str | None = None


class PromptTemplate(BaseModel):
    """A prompt file: ``### system`` and ``### user`` sections with ``{{var}}`` placeholders."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    prompt_id: str
    version: str
    sha256: str
    system: str
    user: str

    def variables(self) -> frozenset[str]:
        """Return the placeholder names used in the system and user sections."""
        return frozenset(PLACEHOLDER.findall(self.system) + PLACEHOLDER.findall(self.user))

    def render(self, **values: str) -> tuple[Message, ...]:
        """Fill the placeholders strictly.

        Args:
            **values: One string per placeholder.

        Returns:
            The system message (when the file has a system section) followed by the user message.

        Raises:
            PromptError: A placeholder has no value, or a value matches no placeholder.

        Examples:
            >>> t = PromptTemplate(
            ...     prompt_id="e", version="v1", sha256="0", system="", user="Hallo {{n}}"
            ... )
            >>> t.render(n="Welt")[0].content
            'Hallo Welt'
        """
        wanted = self.variables()
        missing, extra = sorted(wanted - values.keys()), sorted(values.keys() - wanted)
        if missing or extra:
            msg = (
                f"prompt {self.prompt_id}_{self.version}: "
                f"missing variable(s) {missing}, extra variable(s) {extra}"
            )
            raise PromptError(msg)

        def fill(text: str) -> str:
            return PLACEHOLDER.sub(lambda m: values[m.group(1)], text)

        out = [Message(role="user", content=fill(self.user))]
        if self.system:
            out.insert(0, Message(role="system", content=fill(self.system)))
        return tuple(out)
