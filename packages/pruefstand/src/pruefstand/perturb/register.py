"""``register``: formal Sie <-> informal du, rules first, the model for what rules cannot conjugate.

Rules (``data/register_verbs.yaml``): the finite verb directly in front of ``Sie`` (inverted order,
"Können Sie ...") is conjugated from the table, ``für Sie`` / ``mit Ihnen`` and ``Ihr...`` are
swapped. Anything else (``ob Sie ... haben``, a verb the table lacks, a sentence-initial
``Sie``/``Ihr`` that may mean "they") goes to the model. The text of a questions that is already
informal ("Kannst du ...") is turned into Sie the same way.
"""

import re
from functools import cache
from pathlib import Path
from typing import override

import numpy as np
import yaml

from pruefstand.core.protocols import LLMClientLike
from pruefstand.perturb.draft import Draft, RuleResult
from pruefstand.perturb.llm_base import LLMRewritePerturbation

_FILE = Path(__file__).resolve().parent / "data" / "register_verbs.yaml"
_ACC_PREP = "für|ohne|gegen|durch|um"
_DAT_PREP = "mit|bei|von|nach|zu|aus|neben|seit|gegenüber"
_ACC = _ACC_PREP.split("|")
_FORMAL = re.compile(r"\b(?:Sie|Ihnen|Ihr(?:e|en|em|er|es)?)\b")
_INFORMAL = re.compile(r"\b(?:du|dich|dir|dein(?:e|en|em|er|es)?)\b", re.IGNORECASE)
_SENTENCE_START = re.compile(r"(?:^|[.?!]\s+)$")
_AMBIGUOUS = re.compile(
    r"\b(?:sich|sie|ihnen|ihr(?:e|en|em|er|es)?)\b"  # they / her / reflexive
    r"|(?:^|[.?!]\s+)Ihnen\b"  # sentence-initial: "to them" or "to you"
    r"|\b(?:Sie|du) (?:und|oder|sowie)\b|\b(?:und|oder|sowie) (?:Sie|du)\b"  # joint subject
    r"|[\"\u201e\u201c\u201d\u00bb\u00ab]"  # quoted speech
)


@cache
def _tables() -> tuple[dict[str, str], dict[str, str]]:
    verbs = yaml.safe_load(_FILE.read_text(encoding="utf-8"))["verbs"]
    return (
        {v["sie"]: v["du"] for v in verbs},
        {v["du"]: v["sie"] for v in verbs},
    )


def _case(src: str, word: str) -> str:
    return word[:1].upper() + word[1:] if src[:1].isupper() else word


def _at_sentence_start(text: str, pos: int) -> bool:
    return _SENTENCE_START.search(text[:pos]) is not None


def _to_du(text: str) -> RuleResult:
    sie_to_du, _ = _tables()

    def possessive(m: re.Match[str]) -> str:
        return m.group(0) if _at_sentence_start(text, m.start()) else "dein" + (m.group(1) or "")

    def verb(m: re.Match[str]) -> str:
        du = sie_to_du.get(m.group(1).lower())
        return f"{_case(m.group(1), du)} du" if du else m.group(0)

    def prep(m: re.Match[str]) -> str:
        return f"{m.group(1)} {'dich' if m.group(1).lower() in _ACC else 'dir'}"

    out = re.sub(r"\bIhr(e|en|em|er|es)?\b", possessive, text)
    out = re.sub(r"\b(\w+) Sie\b", verb, out)
    out = re.sub(rf"\b((?i:{_ACC_PREP}|{_DAT_PREP})) Sie\b", prep, out)
    out = re.sub(r"\bIhnen\b", "dir", out)
    if _FORMAL.search(out):
        return RuleResult(text=text, variant="du", needs_llm=True)
    return RuleResult(text=out, variant="du")


def _to_sie(text: str) -> RuleResult:
    _, du_to_sie = _tables()

    def verb(m: re.Match[str]) -> str:
        sie = du_to_sie.get(m.group(1).lower())
        return f"{_case(m.group(1), sie)} Sie" if sie else m.group(0)

    def possessive(m: re.Match[str]) -> str:
        return "Ihr" + (m.group(1) or "")

    out = re.sub(rf"\b({_ACC_PREP}) (dich)\b|\b({_DAT_PREP}) (dir)\b", _prep_sie, text)
    out = re.sub(r"\b(\w+) du\b", verb, out, flags=re.IGNORECASE)
    out = re.sub(r"\bdein(e|en|em|er|es)?\b", possessive, out, flags=re.IGNORECASE)
    if _INFORMAL.search(out):
        return RuleResult(text=text, variant="sie", needs_llm=True)
    return RuleResult(text=out, variant="sie")


def _prep_sie(m: re.Match[str]) -> str:
    prep, pron = (m.group(1), "Sie") if m.group(1) else (m.group(3), "Ihnen")
    return f"{prep} {pron}"


def rule_register(text: str) -> RuleResult | None:
    """Apply the register rules.

    Args:
        text: NFC question.

    Returns:
        None without any Sie/du marker; else the rewritten text with the direction (``du`` or
        ``sie``), or ``needs_llm=True`` (text unchanged) when the rules cannot finish.

    Examples:
        >>> rule_register("Können Sie mir sagen, wann die Frist endet?").text
        'Kannst du mir sagen, wann die Frist endet?'
        >>> rule_register("Wie lange ist die Frist?") is None
        True
    """
    formal = _FORMAL.search(text) is not None
    if not formal and _INFORMAL.search(text) is None:
        return None
    variant = "du" if formal else "sie"
    if _AMBIGUOUS.search(text):  # lowercase sie / sich / ihr: meaning or reflexive agreement
        return RuleResult(text=text, variant=variant, needs_llm=True)
    return _to_du(text) if formal else _to_sie(text)


class Register(LLMRewritePerturbation):
    """Switch between Sie and du."""

    name = "register"

    @override
    async def adraft(self, text: str, llm: LLMClientLike, rng: np.random.Generator) -> Draft | None:
        """Return the rule rewrite, or the model's when the rules cannot conjugate."""
        rule = rule_register(text)
        if rule is None:
            return None
        if not rule.needs_llm:
            return Draft(text=rule.text, variant=rule.variant)
        out = await self.rewriter.rewrite(llm, f"register_{rule.variant}_de", question=text)
        return Draft(
            text=out.text, model=out.model, local=out.local, used_llm=True, variant=rule.variant
        )
