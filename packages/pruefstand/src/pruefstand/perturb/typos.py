"""``typos``: one seeded keyboard-style edit in one word of six or more letters.

Edit types (D392): deletion, adjacent transposition, substitution by a neighbouring key of the
QWERTZ layout. Each is edit distance 1 (Damerau-Levenshtein). The first letter is never edited.
Numbers, ``§`` and every word that resolves to a law name or contains a capital after its first
letter (``KSchG``, ``GmbHG``, ``DSGVO``) are never touched; neither are runs over 40 letters
or words inside URLs, e-mail addresses, domains and canary-like tokens (D394).
"""

import re

import numpy as np

from pruefstand.core.citations.aliases import resolve_law
from pruefstand.core.models.perturb import PerturbResult
from pruefstand.perturb._common import finish, nfc

_ROWS = ("qwertzuiop", "asdfghjkl", "yxcvbnm")
_MAX_LETTERS = 40  # longer runs are not words; also keeps the work per edit constant (D392)
_WORD = re.compile(r"(?<![\d_])[^\W\d_]{6,}(?![\d_])")
_TOKEN = re.compile(r"\S+")
# URLs, e-mail addresses, domains and canary-like tokens (CANARY-XX-abcdef) are never edited
_PROTECTED = re.compile(
    r"@|://|www\.|[A-Za-z0-9-]\.[A-Za-z]{2,}|[A-Z]{2,}[-_]|[-_][0-9a-fA-F]{6,}(?!\w)"
)


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


def _candidates(source: str) -> list[tuple[int, int]]:
    """Return the spans of the editable words (outside protected whitespace-delimited tokens)."""
    spans: list[tuple[int, int]] = []
    for token in _TOKEN.finditer(source):
        if _PROTECTED.search(token.group(0)):
            continue
        for m in _WORD.finditer(token.group(0)):
            if _eligible(m.group(0)):
                spans.append((token.start() + m.start(), token.start() + m.end()))
    return spans


class Typos:
    """Insert one keyboard typo into a long word."""

    name = "typos"
    version = "1"
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
