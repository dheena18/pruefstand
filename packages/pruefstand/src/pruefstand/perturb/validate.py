"""Validity check of an LLM rewrite: transformation present, numbers kept, meaning kept (T4.5).

Three layers, cheapest first: (1) ``static_check`` (rule-specific regex, no new or lost numbers or
paragraph signs, the question stays a question); (2) the equivalence check by a model of a family
different from the rewriting model (``RewriteValidator``, prompt ``perturb_equivalence_de_v1``);
(3) a seeded 10 % sample of accepted rewrites is cross-checked with the second model and logged
for the human review of T4.7b. A failed rewrite is ``changed=False`` with the reason in ``notes``.
"""

import re
from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, ConfigDict

from pruefstand.core.errors import ConfigError, LLMError, PolicyViolation
from pruefstand.core.hashing import stable_hash
from pruefstand.core.logging import get_logger
from pruefstand.core.models.llm import LLMRequest, LLMRole
from pruefstand.core.protocols import LLMClientLike
from pruefstand.llm.families import family_of
from pruefstand.perturb.draft import Draft
from pruefstand.perturb.rewriter import PROMPT_VERSION, PROMPTS

log = get_logger(__name__)

_NUMBER = re.compile(r"§§?\s*\d+[a-z]?|\d+(?:[.,]\d+)*")
_FORMAL = re.compile(r"\b(?:Sie|Ihnen|Ihr(?:e|en|em|er|es)?)\b")
_INFORMAL = re.compile(r"\b(?:du|dich|dir|dein(?:e|en|em|er|es)?)\b", re.IGNORECASE)
_GENDER = re.compile(r"[*:_]innen|ende[n]?\b|innen und")
_MIN_RATIO, _MAX_RATIO, _SLACK = 0.3, 3.0, 40
TRANSFORMATIONS = {
    "compound_split": "Zusammengesetzte Wörter durch analytische Umschreibungen ersetzt",
    "register": "Anrede gewechselt (Sie und du)",
    "gender": "Generische Maskulina durch geschlechtergerechte Formen ersetzt",
    "colloquial": "In Alltagssprache umformuliert",
}


class Verdict(BaseModel):
    """Result of the validity check."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    valid: bool
    reason: str = "ok"
    validator: str | None = None
    cross_check: Literal[0, 1] | None = None
    detail: str = ""


class Equivalence(BaseModel):
    """Answer of the equivalence check."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    reason: str = ""
    score: Literal[0, 1]


def _numbers(text: str) -> set[str]:
    return {re.sub(r"\s+", "", m) for m in _NUMBER.findall(text)}


def _compound_done(draft: Draft) -> bool:
    return any(t not in draft.text for t in draft.targets)


def _gender_done(draft: Draft) -> bool:
    return _GENDER.search(draft.text) is not None


def _register_done(draft: Draft) -> bool:
    formal = _FORMAL.search(draft.text) is not None
    informal = _INFORMAL.search(draft.text) is not None
    return informal and not formal if draft.variant == "du" else formal and not informal


def _transformation_present(name: str, draft: Draft) -> bool:
    checks: dict[str, Callable[[Draft], bool]] = {
        "compound_split": _compound_done,
        "register": _register_done,
        "gender": _gender_done,
    }
    check = checks.get(name)
    return check(draft) if check else True


def static_check(name: str, source: str, draft: Draft) -> str | None:
    """Run the rule checks of one rewrite.

    Args:
        name: Perturbation name.
        source: The original question.
        draft: The rewrite.

    Returns:
        None when all checks pass, else the reason: ``empty``, ``multiline``, ``unchanged``,
        ``number_changed``, ``length``, ``transformation_missing`` or ``question_lost``.

    Examples:
        >>> static_check("colloquial", "Gilt § 622 BGB?", Draft(text="Gilt das nach 30 Tagen?"))
        'number_changed'
    """
    out = draft.text
    reason = _shape_problem(source, out)
    if reason is not None:
        return reason
    if not _transformation_present(name, draft):
        return "transformation_missing"
    if source.rstrip().endswith("?") and not out.rstrip().endswith("?"):
        return "question_lost"
    return None


def _shape_problem(source: str, out: str) -> str | None:
    if not out.strip():
        return "empty"
    if "\n" in out:
        return "multiline"
    if out == source:
        return "unchanged"
    if _numbers(source) != _numbers(out):
        return "number_changed"
    if not _MIN_RATIO * len(source) <= len(out) <= _MAX_RATIO * len(source) + _SLACK:
        return "length"
    return None


class RewriteValidator:
    """Equivalence check by a model whose family differs from the rewriting model.

    Args:
        llm: Client of the local judge ``model`` (public rewrites).
        model: The judge model id (``ollama/<tag>``).
        second: ``(client, model)`` of the second GitHub Models model; it validates locally written
            rewrites (public items only) and takes the cross-check sample.
        cross_check_rate: Share of accepted rewrites that the second model also checks.
        seed: Seed of the sample.
    """

    def __init__(
        self,
        llm: LLMClientLike,
        model: str,
        *,
        second: tuple[LLMClientLike, str] | None = None,
        cross_check_rate: float = 0.1,
        seed: int = 0,
    ) -> None:
        self._primary = (llm, model)
        self._second = second
        self._rate = cross_check_rate
        self._seed = seed

    async def judge(self, name: str, source: str, draft: Draft) -> Verdict:
        """Check that ``draft`` keeps the meaning of ``source``.

        Args:
            name: Perturbation name.
            source: The original question.
            draft: A model-written rewrite that passed ``static_check``.

        Returns:
            The verdict; ``not_equivalent`` for score 0, ``no_independent_validator`` for a local
            rewrite no other-family model may check.

        Raises:
            ConfigError: Rewriter and every validator are of the same family (public rewrite).
            LLMError: The check call failed (``QuotaExhausted`` for the second model).
        """
        if draft.model is None:
            return Verdict(valid=True, reason="rule_only")
        family = family_of(draft.model)
        picked = self._pick(family)
        if picked is None:
            if draft.local:
                return Verdict(valid=False, reason="no_independent_validator")
            msg = f"validator and rewriter are both of family '{family}' (rewriter {draft.model})"
            raise ConfigError(msg)
        llm, model = picked
        try:
            eq = await self._ask(llm, model, name, source, draft)
        except PolicyViolation:  # private text may not go to the external second model
            return Verdict(valid=False, reason="no_independent_validator")
        if eq.score == 0:
            return Verdict(valid=False, reason="not_equivalent", validator=model, detail=eq.reason)
        cross = await self._cross_check(name, source, draft, picked)
        return Verdict(valid=True, validator=model, cross_check=cross, detail=eq.reason)

    def _pick(self, rewriter_family: str) -> tuple[LLMClientLike, str] | None:
        for llm, model in (self._primary, *([self._second] if self._second else [])):
            if family_of(model) != rewriter_family:
                return llm, model
        return None

    async def _ask(
        self, llm: LLMClientLike, model: str, name: str, source: str, draft: Draft
    ) -> Equivalence:
        messages = PROMPTS.get("perturb_equivalence_de", PROMPT_VERSION).render(
            original=source, rewrite=draft.text, transformation=TRANSFORMATIONS[name]
        )
        req = LLMRequest(
            role=LLMRole.PERTURB,
            model=model,
            messages=messages,
            temperature=0.0,
            max_tokens=256,
            seed=0,
            prompt_id="perturb_equivalence_de",
            prompt_version=PROMPT_VERSION,
            response_format="json",
        )
        return await llm.complete_json(req, Equivalence)

    def _sampled(self, name: str, source: str, draft: Draft) -> bool:
        draw = int(stable_hash("cross_check", self._seed, name, source, draft.text), 16)
        return draw / 16**16 < self._rate

    async def _cross_check(
        self, name: str, source: str, draft: Draft, picked: tuple[LLMClientLike, str]
    ) -> Literal[0, 1] | None:
        second = self._second
        if second is None or second[1] == picked[1] or not self._sampled(name, source, draft):
            return None
        if draft.model is not None and family_of(second[1]) == family_of(draft.model):
            return None
        try:
            eq = await self._ask(second[0], second[1], name, source, draft)
        except LLMError as err:  # an unavailable second model never blocks the main verdict
            log.warning("perturb_cross_check_failed", perturbation=name, error=type(err).__name__)
            return None
        log.info(
            "perturb_cross_check",
            perturbation=name,
            rewriter=draft.model,
            validator=second[1],
            score=eq.score,
            source=source,
            rewrite=draft.text,
        )
        return eq.score
