"""``gender``: generic masculine plurals become gender-fair forms in a seeded style (T4.5).

Styles: ``star`` "Mitarbeiter*innen", ``colon`` "Mitarbeiter:innen", ``partizip`` "Mitarbeitende",
``pair`` "Mitarbeiterinnen und Mitarbeiter". The rule table (``data/gender_nouns.yaml``, 50 frequent
nouns) handles plural forms. A singular with an article ("der Mitarbeiter"), which needs article and
verb agreement, and every noun outside the table (found only by the model) go to the model.
"""

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import override

import numpy as np
import yaml

from pruefstand.core.protocols import LLMClientLike
from pruefstand.perturb.draft import Draft, RuleResult
from pruefstand.perturb.llm_base import LLMRewritePerturbation

STYLES = ("star", "colon", "partizip", "pair")
_FILE = Path(__file__).resolve().parent / "data" / "gender_nouns.yaml"
_WORD = re.compile(r"\b[A-ZÄÖÜ][a-zäöüß]+\b")
_JOINERS = "*:_/·"
_SINGULAR = re.compile(
    r"^(?:der|dem|den|des|ein|einem|einen|einer|eines|jede[rmns]?|dies(?:er|em|en|es)|"
    r"welche[rmns]|kein(?:em|en|er|es)?|vom|zum|beim|im|am|(?:mein|dein|sein|unser|euer|ihr)"
    r"(?:em|en|er|es)?)$"
)
_WEAK = re.compile(r"^(?:die|diese|alle|keine|jene|(?:mein|dein|sein|unser|euer|ihr)e)$")
_STRONG = re.compile(
    r"^(?:viele|einige|mehrere|etliche|zwei|drei|vier|fünf|sechs|sieben|acht|neun|zehn|\d+)$"
)
_OTHER_PLURAL = re.compile(r"^welche$")
_ADJECTIVE = re.compile(r"^[a-zäöüß]+(?:e|en|er|es|em)$")
_MAX_ADJECTIVES = 3


@dataclass(frozen=True)
class Noun:
    """One table entry: ``m`` singular, ``pl`` plural, ``f_pl`` feminine plural, optional forms."""

    m: str
    pl: str
    f_pl: str
    stem: str
    part: str | None

    @property
    def dative(self) -> str:
        """Dative plural of the masculine."""
        return self.pl if self.pl.endswith("n") else self.pl + "n"


@cache
def load_nouns() -> tuple[Noun, ...]:
    """Return the rule table.

    Returns:
        The nouns of ``data/gender_nouns.yaml`` (at least 40).
    """
    rows = yaml.safe_load(_FILE.read_text(encoding="utf-8"))["nouns"]
    return tuple(
        Noun(r["m"], r["pl"], r["f_pl"], r.get("stem", r["pl"]), r.get("part")) for r in rows
    )


@cache
def _lookup() -> dict[str, tuple[Noun, str]]:
    """Surface form -> (noun, kind) with kind in ``pl``, ``dat``, ``sg``."""
    table: dict[str, tuple[Noun, str]] = {}
    for n in load_nouns():
        for form, kind in ((n.m, "sg"), (n.m + "s", "sg"), (n.dative, "dat"), (n.pl, "pl")):
            table[form] = (n, kind)
    return table


def _form(noun: Noun, style: str, *, dative: bool, weak: bool) -> str:
    if style == "star":
        return noun.stem + "*innen"
    if style == "colon":
        return noun.stem + ":innen"
    if style == "partizip":
        return (noun.part or noun.pl) + ("n" if dative or weak else "")
    return f"{noun.f_pl} und {noun.dative if dative else noun.pl}"


def _number_context(text: str, pos: int) -> tuple[str, str]:
    """Return ``(number, strength)`` from the determiner directly before the noun.

    Only adjectives (at most three) may stand between determiner and noun; a comma, a noun, a
    preposition phrase or any other word ends the search with ``("none", "")``. ``number`` is
    ``sg``, ``pl`` or ``none``; ``strength`` is ``weak``, ``strong`` or ``other`` for a plural.
    """
    words = re.findall(r"[\wäöüß]+|[,.;:!?]", text[:pos])[-(_MAX_ADJECTIVES + 1) :]
    for original in reversed(words):
        word = original.lower()
        if _SINGULAR.match(word):
            return "sg", ""
        for pattern, strength in ((_WEAK, "weak"), (_STRONG, "strong"), (_OTHER_PLURAL, "other")):
            if pattern.match(word):
                return "pl", strength
        if not (original[0].islower() and _ADJECTIVE.match(word)):
            break
    return "none", ""


Hit = tuple[re.Match[str], Noun, bool, str]


def _scan(text: str) -> tuple[list[Hit], bool]:
    """Return the plural hits (match, noun, dative, strength) and whether the model is needed.

    A noun whose singular equals its plural is rule-converted only behind an explicit plural
    determiner or number; every other context is left to the model (fail safe, D741/D745).
    """
    hits: list[Hit] = []
    unsure = False
    for m in _WORD.finditer(text):
        found = _lookup().get(m.group(0))
        if found is None or text[m.end() : m.end() + 1] in _JOINERS:
            continue
        noun, kind = found
        if kind == "dat":
            hits.append((m, noun, True, "weak"))
            continue
        number, strength = _number_context(text, m.start())
        if kind == "sg" or number == "sg" or (noun.m == noun.pl and number != "pl"):
            unsure = True
            continue
        hits.append((m, noun, False, strength or "other"))
    return hits, unsure


def _participle_ok(hit: Hit) -> bool:
    """The participle exists and its declension is certain (weak or strong context)."""
    _, noun, dative, strength = hit
    return bool(noun.part) and (dative or strength in ("weak", "strong"))


def pick_style(rng: np.random.Generator, allowed: tuple[str, ...] = STYLES) -> str:
    """Return one of ``allowed`` drawn from ``rng`` (same seed, same style)."""
    return allowed[int(rng.integers(len(allowed)))]


def rule_gender(text: str, rng: np.random.Generator) -> RuleResult | None:
    """Apply the gender rules.

    Args:
        text: NFC question.
        rng: Randomness for the style.

    Returns:
        None when no table noun occurs; ``needs_llm=True`` (text unchanged) when a singular needs
        article agreement; else the text with every plural noun in the drawn style.

    Examples:
        >>> r = rule_gender("Wie viele Mitarbeiter braucht der Betrieb?", np.random.default_rng(0))
        >>> r is not None and r.variant in STYLES
        True
    """
    hits, singular = _scan(text)
    if not hits and not singular:
        return None
    allowed = tuple(s for s in STYLES if s != "partizip" or all(_participle_ok(h) for h in hits))
    style = pick_style(rng, allowed)
    if singular:
        return RuleResult(text=text, variant=style, needs_llm=True)
    out, last = [], 0
    for m, noun, dative, strength in hits:
        form = _form(noun, style, dative=dative, weak=strength == "weak")
        out += [text[last : m.start()], form]
        last = m.end()
    return RuleResult(text="".join(out) + text[last:], variant=style)


class Gender(LLMRewritePerturbation):
    """Gender-fair rewriting."""

    name = "gender"

    @override
    async def adraft(self, text: str, llm: LLMClientLike, rng: np.random.Generator) -> Draft | None:
        """Return the rule rewrite, or the model's for singulars with articles."""
        rule = rule_gender(text, rng)
        if rule is None:
            return None
        if not rule.needs_llm:
            return Draft(text=rule.text, variant=rule.variant)
        out = await self.rewriter.rewrite(llm, f"gender_{rule.variant}_de", question=text)
        return Draft(
            text=out.text, model=out.model, local=out.local, used_llm=True, variant=rule.variant
        )
