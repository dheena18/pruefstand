"""Validity checks for constructed negatives (T5.3 review of #107, D863, D864)."""

from rq2.construct import STOPWORDS, norm, tokens

COVERAGE_MAX = 0.6
_CLAUSE_BREAKS = (",", "(", ";", "–", " - ")


def content_tokens(text: str) -> set[str]:
    """Return the normalised tokens of ``text`` that are not stopwords."""
    return {t for t in tokens(text) if t not in STOPWORDS}


def key_tokens(text: str) -> set[str]:
    """Return the numbers and the capitalised words (not the first word) of ``text``, normalised."""
    words = text.split()
    keys = {w for w in words[1:] if w[:1].isupper()} | {
        w for w in words if any(c.isdigit() for c in w)
    }
    return {t for w in keys for t in tokens(w)}


def coverage(answer: str, passage: str) -> float:
    """Return the share of the answer's content tokens that occur in ``passage`` (0.0 if none)."""
    content = content_tokens(answer)
    return len(content & set(tokens(passage))) / len(content) if content else 0.0


def may_support(answer: str, passage: str) -> bool:
    """True when ``passage`` might support ``answer``.

    That is: the answer string is in it, it covers at least 60 % of the answer's content tokens,
    or it holds every number and name of the answer.
    """
    if norm(answer) in norm(passage):
        return True
    keys = key_tokens(answer)
    passage_tokens = set(tokens(passage))
    return coverage(answer, passage) >= COVERAGE_MAX or bool(keys and keys <= passage_tokens)


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


def has_answer_content(candidate: str) -> bool:
    """True iff ``candidate`` has at least one non-stopword token."""
    return bool(content_tokens(candidate))
