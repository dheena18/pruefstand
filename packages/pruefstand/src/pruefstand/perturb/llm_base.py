"""Base of the four LLM-assisted perturbations: draft, then validity check (T4.5)."""

from abc import ABC, abstractmethod

import numpy as np

from pruefstand.core.errors import ConfigError
from pruefstand.core.models.perturb import PerturbResult
from pruefstand.core.protocols import LLMClientLike
from pruefstand.perturb._common import nfc
from pruefstand.perturb.draft import Draft
from pruefstand.perturb.rewriter import Rewriter
from pruefstand.perturb.validate import RewriteValidator, Verdict, static_check


class LLMRewritePerturbation(ABC):
    """A rules-first, LLM-second perturbation.

    Subclasses implement ``adraft`` (rules, then the model where the rules stop); this class runs
    the validity check and builds the ``PerturbResult``. The two steps are public so the rewrite
    pass and the validate pass can run apart (ADR-0019).

    Args:
        rewriter: The rewrite model (and optional local model).
        validator: Equivalence check; may be None only while every draft is rule-only.
    """

    name: str
    version: str = "v1"
    uses_llm: bool = True

    def __init__(self, rewriter: Rewriter, validator: RewriteValidator | None = None) -> None:
        self.rewriter = rewriter
        self.validator = validator

    def apply(self, text: str, rng: np.random.Generator) -> PerturbResult:
        """Not available: ``{name}`` may call a model; use ``aapply``.

        Raises:
            ConfigError: Always.
        """
        del text, rng
        msg = f"perturbation '{self.name}' may call a model; use aapply"
        raise ConfigError(msg)

    @abstractmethod
    async def adraft(self, text: str, llm: LLMClientLike, rng: np.random.Generator) -> Draft | None:
        """Return the rewrite of NFC ``text``, or None when the perturbation does not apply.

        Raises:
            LLMError: The model call failed.
        """

    async def acheck(self, source: str, draft: Draft) -> Verdict:
        """Validate ``draft`` against ``source`` (static checks, then the equivalence check).

        Raises:
            ConfigError: A model-written draft but no validator, or no other-family validator.
            LLMError: The equivalence call failed.
        """
        reason = static_check(self.name, source, draft)
        if reason is not None:
            return Verdict(valid=False, reason=reason)
        if not draft.used_llm:
            return Verdict(valid=True, reason="rule_only")
        if self.validator is None:
            msg = f"perturbation '{self.name}' needs a RewriteValidator for model-written text"
            raise ConfigError(msg)
        return await self.validator.judge(self.name, source, draft)

    def result(self, source: str, draft: Draft | None, verdict: Verdict | None) -> PerturbResult:
        """Return the rewrite when valid, else ``source`` with the reason in ``notes``."""
        if draft is None or verdict is None:
            return PerturbResult(text=source, changed=False, notes="not_applicable")
        if not verdict.valid:
            return PerturbResult(text=source, changed=False, notes=verdict.reason)
        who = draft.model or "rules"
        notes = f"{draft.variant} {who}".strip()
        return PerturbResult(text=draft.text, changed=True, notes=notes)

    async def aapply(
        self, text: str, llm: LLMClientLike, rng: np.random.Generator
    ) -> PerturbResult:
        """Rewrite ``text`` and validate the rewrite.

        Args:
            text: The question.
            llm: Client of the rewrite model.
            rng: Randomness for seeded choices (gender style).

        Returns:
            The valid rewrite, or ``changed=False`` with the reason (``not_applicable``,
            ``unchanged``, ``not_equivalent``, ``number_changed``, ...) in ``notes``.

        Raises:
            ConfigError: No validator / no other-family validator.
            PolicyViolation: The data guard blocked the call and there is no local model.
            LLMError: A model call failed; ``QuotaExhausted`` when the free quota is used up.
        """
        source = nfc(text)
        draft = await self.adraft(source, llm, rng)
        if draft is None:
            return self.result(source, None, None)
        draft = draft.model_copy(update={"text": nfc(draft.text)})
        return self.result(source, draft, await self.acheck(source, draft))
