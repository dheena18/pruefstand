"""``typos``: one seeded keyboard-style edit in one word of six or more letters.

Edit types (D392): deletion, adjacent transposition, substitution by a neighbouring key of the
QWERTZ layout. Each is edit distance 1 (Damerau-Levenshtein). The first letter is never edited.
Numbers and ``§`` are never touched. Skipped words: every word of a law name or alias, also a
multi-word one (``Bürgerliches Gesetzbuch``), a capital after the first letter (``KSchG``,
``DSGVO``), runs over 40 letters, and words inside URLs, e-mail addresses, domains (also with
non-ASCII endings such as ``kanzlei.köln``) and canary-like tokens, including a canary written with
spaces (``CANARY VN a1b2c3``; D394, T4.4a, D891).
"""

import re
from functools import cache

import numpy as np

from pruefstand.core.citations.aliases import law_aliases, match_law, resolve_law
from pruefstand.core.models.perturb import PerturbResult
from pruefstand.perturb._common import finish, nfc

_ROWS = ("qwertzuiop", "asdfghjkl", "yxcvbnm")
_MAX_LETTERS = 40  # longer runs are not words; also keeps the work per edit constant (D392)
_WORD = re.compile(r"(?<![\d_])[^\W\d_]{6,}(?![\d_])")
_TOKEN = re.compile(r"\S+")
# URLs, e-mail addresses, domains and canary-like tokens (CANARY-XX-abcdef) are never edited
_PROTECTED = re.compile(r"@|://|www\.|[^\W_]\.[^\W\d_]{2,}|[A-Z]{2,}[-_]|[-_][0-9a-fA-F]{6,}(?!\w)")
_HEX = re.compile(r"[0-9a-f]{6,}")
_SHOUT = re.compile(r"[A-Z]{2,}[A-Z0-9_-]*")
_LETTERS = re.compile(r"[^\W\d_]+")
_TRAILING = ".,;:!?)\"'"


def _neighbours() -> dict[str, tuple[str, ...]]:
    found: dict[str, set[str]] = {c: set() for row in _ROWS for c in row}
    for r, row in enumerate(_ROWS):
        for i, key in enumerate(row):
            if i > 0:
                found[key].add(row[i - 1])
            if i + 1 < len(row):
                found[key].add(row[i + 1])
            if r + 1 < len(_ROWS):
                for j in (i - 1, i):
                    if 0 <= j < len(_ROWS[r + 1]):
                        below = _ROWS[r + 1][j]
                        found[key].add(below)
                        found[below].add(key)
    return {k: tuple(sorted(v)) for k, v in found.items()}


QWERTZ_NEIGHBOURS = _neighbours()


def _eligible(word: str) -> bool:
    return len(word) <= _MAX_LETTERS and word[1:].islower() and resolve_law(word) is None


def _options(word: str) -> dict[str, list[str]]:
    """Return every one-edit variant of ``word`` by edit type (first letter untouched)."""
    last = len(word)
    options: dict[str, list[str]] = {"deletion": [], "transposition": [], "substitution": []}
    for i in range(1, last):
        options["deletion"].append(word[:i] + word[i + 1 :])
        if i + 1 < last and word[i] != word[i + 1]:
            options["transposition"].append(word[:i] + word[i + 1] + word[i] + word[i + 2 :])
        for key in QWERTZ_NEIGHBOURS.get(word[i].lower(), ()):
            typed = key.upper() if word[i].isupper() else key
            options["substitution"].append(word[:i] + typed + word[i + 1 :])
    return {kind: found for kind, found in options.items() if found}


@cache
def _law_openers() -> frozenset[str]:
    """First words (casefolded) of all law names and aliases: where a law name can start."""
    return frozenset(
        opener.group(0).casefold()
        for aliases in law_aliases().all_laws().values()
        for alias in aliases
        if (opener := _LETTERS.match(alias)) is not None
    )


def _law_spans(source: str) -> list[tuple[int, int]]:
    """Spans of the law names (any alias, also several words) in ``source``."""
    spans: list[tuple[int, int]] = []
    end = 0
    for word in _LETTERS.finditer(source):
        if word.start() >= end and word.group(0).casefold() in _law_openers():
            found = match_law(source, word.start())
            if found is not None:
                spans.append((word.start(), found[1]))
                end = found[1]
    return spans


def _canary_tail(token: str, previous: str) -> bool:
    """A hex run after an all-caps token is the tail of a canary written with spaces."""
    return bool(
        _HEX.fullmatch(token.rstrip(_TRAILING)) and _SHOUT.fullmatch(previous.rstrip(_TRAILING))
    )


def _candidates(source: str) -> list[tuple[int, int]]:
    """Return the spans of the editable words (outside protected tokens and law names)."""
    spans: list[tuple[int, int]] = []
    laws = _law_spans(source)
    previous = ""
    for token in _TOKEN.finditer(source):
        text, before, previous = token.group(0), previous, token.group(0)
        if _PROTECTED.search(text) or _canary_tail(text, before):
            continue
        for m in _WORD.finditer(text):
            span = (token.start() + m.start(), token.start() + m.end())
            if _eligible(m.group(0)) and not any(a < span[1] and span[0] < b for a, b in laws):
                spans.append(span)
    return spans


class Typos:
    """Insert one keyboard typo into a long word."""

    name = "typos"
    version = "2"
    uses_llm = False

    def apply(self, text: str, rng: np.random.Generator) -> PerturbResult:
        """Edit one word.

        Args:
            text: The question.
            rng: The only source of randomness; the same generator state gives the same edit.

        Returns:
            The result; ``changed`` is False when no word qualifies.

        Examples:
            >>> Typos().apply("Was ist die Kündigungsfrist?", np.random.default_rng(1)).changed
            True
        """
        source = nfc(text)
        words = _candidates(source)
        if not words:
            return finish(source, source)
        start, end = words[int(rng.integers(len(words)))]
        word = source[start:end]
        options = _options(word)
        kind = sorted(options)[int(rng.integers(len(options)))]
        variants = options[kind]
        edited = variants[int(rng.integers(len(variants)))]
        out = source[:start] + edited + source[end:]
        return finish(source, out, notes=f"{kind}: {word} -> {edited}")
