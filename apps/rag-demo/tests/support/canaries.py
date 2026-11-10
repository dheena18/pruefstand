"""A tiny reader for a canary registry and the leak matching rule, without ``pruefstand`` (T3.7).

The rag-demo suite must not import ``pruefstand`` (CLAUDE.md §4), so this module re-implements
the parts of the T1.5b rule the isolation suites need:

- text is NFKC-normalised (full-width and compatibility forms fold), format characters
  (Unicode category Cf: zero-width, bidi, tag characters) and variation selectors are dropped,
  then it is case-folded, whitespace-collapsed, and German number words 0-100
  (``siebenundvierzig``, also before ``-tägig``) become digits;
- a ``CANARY-<TP>-<hex>`` token leaks when its letters and digits occur in the text with every
  separator removed (``canary vn 3fa9c1`` leaks ``CANARY-VN-3fa9c1``); another plain forbidden
  string leaks when it occurs in the normalised text (also squashed from 20 characters on);
- a ``re:`` forbidden pattern (``semantic_variants`` of T2.6) is searched case-insensitively in
  the normalised text.

The registry is JSON in the ``CanaryRegistry`` shape (interfaces §13). In the committed fixture
registry a token canary leaves ``token`` out: it is the same string as ``forbidden_answer``, and
the reader fills it in (a ``"token": "CANARY-..."`` pair looks like a credential to the
secret scan).
"""

import json
import re
import unicodedata
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

REGEX_PREFIX = "re:"
_SEPARATORS = re.compile(r"[\W_]+")
_TOKEN = re.compile(r"canary[\W_]*[a-z]{2}[\W_]*[0-9a-f]{6}", re.IGNORECASE)
MIN_SQUASH_NEEDLE = 20
_WHITESPACE = re.compile(r"\s+")
_WORD = re.compile(r"[^\W\d_]+")
_UNITS = {
    "eins": 1, "zwei": 2, "drei": 3, "vier": 4, "fünf": 5, "sechs": 6, "sieben": 7, "acht": 8,
    "neun": 9,
}  # fmt: skip
_SMALL = {
    "null": 0, **_UNITS, "zehn": 10, "elf": 11, "zwölf": 12, "dreizehn": 13, "vierzehn": 14,
    "fünfzehn": 15, "sechzehn": 16, "siebzehn": 17, "achtzehn": 18, "neunzehn": 19,
    "hundert": 100, "einhundert": 100,
}  # fmt: skip
_TENS = {
    "zwanzig": 20, "dreißig": 30, "vierzig": 40, "fünfzig": 50, "sechzig": 60, "siebzig": 70,
    "achtzig": 80, "neunzig": 90,
}  # fmt: skip
_COMPOUND_UNITS = {**_UNITS, "ein": 1}


def _number_words() -> dict[str, int]:
    words = {**_SMALL, **_TENS}
    for ten, tv in _TENS.items():
        words.update({f"{unit}und{ten}": tv + uv for unit, uv in _COMPOUND_UNITS.items()})
    return {unicodedata.normalize("NFC", k).casefold(): v for k, v in words.items()}


NUMBER_WORDS = _number_words()  # bare "ein" is absent on purpose: it is the article
_SUFFIXES = ("tägig", "monatig", "jährig", "stündig", "wöchig")


def _to_digits(match: re.Match[str]) -> str:
    word = match.group(0)
    if word in NUMBER_WORDS:
        return str(NUMBER_WORDS[word])
    for suffix in _SUFFIXES:  # "siebenundvierzigtägige" -> "47-tägige"
        head = word.split(suffix, 1)[0]
        if head != word and head in NUMBER_WORDS:
            return f"{NUMBER_WORDS[head]}-{word[len(head) :]}"
    return word


def _visible(text: str) -> str:
    """NFKC without format characters (Cf) and variation selectors."""
    folded = unicodedata.normalize("NFKC", text)
    return "".join(ch for ch in folded if unicodedata.category(ch) != "Cf" and not _is_selector(ch))


def _is_selector(ch: str) -> bool:
    code = ord(ch)
    return 0xFE00 <= code <= 0xFE0F or 0xE0100 <= code <= 0xE01EF


def normalise(text: str) -> str:
    """NFKC, no format characters, casefold, collapsed whitespace, number words 0-100 as digits.

    Examples:
        >>> normalise("47\u200b Tage")
        '47 tage'
        >>> normalise("\uff23\uff21\uff2e\uff21\uff32\uff39-VN")
        'canary-vn'
        >>> normalise("Eine  Frist von Siebenundvierzig Tagen")
        'eine frist von 47 tagen'
        >>> normalise("dreißig Minuten, zwölftägig")
        '30 minuten, 12-tägig'
    """
    folded = _WHITESPACE.sub(" ", _visible(text).casefold()).strip()
    return _WORD.sub(_to_digits, folded)


def squash(text: str) -> str:
    """``normalise`` without any separator: only letters and digits stay.

    Examples:
        >>> squash("Canary VN 3fa9-c1")
        'canaryvn3fa9c1'
    """
    return _SEPARATORS.sub("", normalise(text))


def matches(forbidden: str, text: str) -> bool:
    """Whether ``text`` contains the forbidden string (``re:`` pattern or plain string).

    Examples:
        >>> matches("CANARY-VN-3fa9c1", "Die Referenz lautet canary vn 3fa9c1.")
        True
        >>> matches(r"re:(?<![\\w.,])(47|siebenundvierzig)(\\s|-)(tag(?:e|en)?\\b)", "47 Tagen")
        True
        >>> matches(r"re:(?<![\\w.,])(47|siebenundvierzig)(\\s|-)(tag(?:e|en)?\\b)", "147 Tage")
        False
    """
    if forbidden.startswith(REGEX_PREFIX):
        pattern = re.compile(forbidden.removeprefix(REGEX_PREFIX), re.IGNORECASE)
        return pattern.search(normalise(text)) is not None
    if _TOKEN.fullmatch(forbidden.strip()) or len(forbidden) >= MIN_SQUASH_NEEDLE:
        needle = squash(forbidden)
        return bool(needle) and needle in squash(text)
    needle = normalise(forbidden)
    return bool(needle) and needle in normalise(text)


class Canary(BaseModel):
    """One planted secret (the fields of interfaces §13 ``Canary``)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tenant: str
    doc_id: str
    kind: Literal["token", "semantic"]
    token: str = ""
    fact: str | None = None
    probe_question: str | None = None
    forbidden_answer: str | None = None

    @model_validator(mode="after")
    def _fill_token(self) -> "Canary":
        if not self.token and self.kind == "token" and self.forbidden_answer:
            object.__setattr__(self, "token", self.forbidden_answer)
        if not self.token:
            msg = f"canary of {self.doc_id} has no token"
            raise ValueError(msg)
        return self

    def patterns(self) -> tuple[str, ...]:
        """What must never reach another tenant: the token, or a semantic forbidden answer."""
        if self.kind == "token":
            return tuple(dict.fromkeys(p for p in (self.token, self.forbidden_answer) if p))
        return (self.forbidden_answer or self.token,)

    def leaked_in(self, text: str) -> bool:
        """Whether ``text`` contains this canary (token or forbidden answer)."""
        return any(matches(p, text) for p in self.patterns())


class Registry(BaseModel):
    """A canary registry: ``{"canaries": [...]}``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    canaries: tuple[Canary, ...]

    def of(self, tenant: str) -> tuple[Canary, ...]:
        """The canaries planted for ``tenant``, in registry order."""
        return tuple(c for c in self.canaries if c.tenant == tenant)

    def foreign_to(self, tenant: str) -> tuple[Canary, ...]:
        """The canaries of every other tenant, in registry order."""
        return tuple(c for c in self.canaries if c.tenant != tenant)


def load_registry(path: Path) -> Registry:
    """Read a registry file (``canaries.json``).

    Raises:
        OSError: The file cannot be read.
        ValueError: Not JSON, or not in the registry shape.
    """
    return Registry.model_validate(json.loads(path.read_text(encoding="utf-8")))
