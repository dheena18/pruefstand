"""Validity checks for constructed negatives (T5.3 review of #107, D863, D864)."""

import re

from rq2.construct import STOPWORDS, norm, tokens

COVERAGE_MAX = 0.6
_CLAUSE_BREAKS = (",", "(", ";", "–", " - ")
NUMBER_TOLERANCE = 0.1
_NUMBER = re.compile(r"\d+(?:\.\d{3})*(?:,\d+)?")
_DANGLING_NEGATION = re.compile(r"\b(?:nicht|kein\w*)\s*(?:[,.;:)]|$)")


def content_tokens(text: str) -> set[str]:
    """Return the normalised tokens of ``text`` that are not stopwords."""
    return {t for t in tokens(text) if t not in STOPWORDS}


def names(text: str) -> set[str]:
    """Return the capitalised words of ``text`` after the first word (normalised, ≥ 3 letters)."""
    words = text.split()[1:]
    return {t for w in words if w[:1].isupper() for t in tokens(w) if len(t) >= 3 and t.isalpha()}


def numbers(text: str) -> list[float]:
    """Return the numbers of ``text`` (German format: ``10.500`` = 10500, ``9,7`` = 9.7)."""
    return [float(m.replace(".", "").replace(",", ".")) for m in _NUMBER.findall(text)]


def near_number(answer: str, passage: str) -> bool:
    """True iff some number of ``passage`` lies within ± 10 % of a non-zero number of ``answer``."""
    found = numbers(passage)
    return any(abs(p - a) <= NUMBER_TOLERANCE * abs(a) for a in numbers(answer) if a for p in found)


def coverage(answer: str, passage: str) -> float:
    """Return the share of the answer's content tokens that occur in ``passage`` (0.0 if none)."""
    content = content_tokens(answer)
    return len(content & set(tokens(passage))) / len(content) if content else 0.0


def may_support(answer: str, passage: str) -> bool:
    """True when ``passage`` might support ``answer`` (review of #107, D864).

    That is: the answer string is in it, it covers at least 60 % of the answer's content tokens,
    it names any capitalised name of the answer, or it has a number within ± 10 % of one of the
    answer's numbers.
    """
    if norm(answer) in norm(passage):
        return True
    passage_tokens = set(tokens(passage))
    return (
        coverage(answer, passage) >= COVERAGE_MAX
        or bool(names(answer) & passage_tokens)
        or near_number(answer, passage)
    )


def edit_in_first_clause(original: str, edited: str) -> bool:
    """True iff the edit starts in the first clause of ``original``.

    The first differing character must lie before the first comma, bracket, semicolon or dash,
    so a parenthesis or relative clause is never the only negated part.
    """
    first_diff = next(
        (i for i, (a, b) in enumerate(zip(original, edited, strict=False)) if a != b),
        min(len(original), len(edited)),
    )
    breaks = [original.find(b) for b in _CLAUSE_BREAKS if b in original]
    return first_diff < min(breaks, default=len(original))


def negation_ok(original: str, edited: str) -> bool:
    """True iff a negation edit starts in the first clause and leaves no dangling negation.

    A ``nicht`` / ``kein…`` right before a comma, a full stop or the end ("..., die ... war nicht,
    ist ...") is rejected, and so is any text with "sondern" ("nicht X, sondern Y").
    """
    if "sondern" in edited.lower():  # "nicht X, sondern Y" breaks when the negation moves
        return False
    return edit_in_first_clause(original, edited) and not _DANGLING_NEGATION.search(edited)


def has_answer_content(candidate: str) -> bool:
    """True iff ``candidate`` has at least one non-stopword token."""
    return bool(content_tokens(candidate))
