"""Models shared by the LLM-assisted perturbations: rewrite draft and rule result (T4.5)."""

from pydantic import BaseModel, ConfigDict


class Draft(BaseModel):
    """A rewritten text before the validity check.

    Attributes:
        text: The rewrite (NFC).
        model: The model that wrote it; None for a rule-only rewrite.
        local: True when the local model wrote it because the data guard blocked the external one.
        used_llm: True when a model call produced ``text``.
        variant: Direction or style (``du``/``sie``, ``star``/``colon``/``partizip``/``pair``).
        targets: Words the rewrite was asked to replace (compound split).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    model: str | None = None
    local: bool = False
    used_llm: bool = False
    variant: str = ""
    targets: tuple[str, ...] = ()


class RuleResult(BaseModel):
    """Outcome of a rule step (``register``, ``gender``).

    ``needs_llm`` means the rules found the transformation applicable but cannot finish it; ``text``
    is then the unchanged input.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    variant: str
    needs_llm: bool = False
