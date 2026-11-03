"""Dictionary compound splitter (offline, deterministic): "Kündigungsschutzgesetz" -> parts.

The lexicon ``lexicon_de.txt`` is package data (own list of German legal and everyday word stems,
MIT like the rest of the repo, a few kB). A word is split only if the lexicon covers it completely;
parts are joined by the linking elements (Fugenelemente) ``s es n en e er ens``. Among all complete
segmentations the one with the fewest parts wins, then the fewest linking characters (so
"Rahmenvertrag" is rahmen+vertrag, not rahm+en+vertrag), then the alphabetically first.
"""

from functools import lru_cache
from importlib import resources

from rag_demo.analysis.normalise import fold

MIN_WORD = 10
MIN_PART = 3
MAX_WORD = 60
_FUGEN = ("", "s", "es", "n", "en", "e", "er", "ens")


def _load() -> frozenset[str]:
    text = (resources.files("rag_demo.analysis") / "lexicon_de.txt").read_text(encoding="utf-8")
    words = {line.strip() for line in text.splitlines() if line.strip()}
    return frozenset(words | {fold(w) for w in words})


_LEXICON = _load()
_Plan = tuple[int, int, tuple[str, ...]]


def _best(word: str, start: int) -> _Plan | None:
    """Best (parts, linking chars, part tuple) covering ``word[start:]``, or ``None``."""
    best: _Plan | None = None
    for end in range(start + MIN_PART, len(word) + 1):
        segment = word[start:end]
        for fugen in _FUGEN if end < len(word) else ("",):
            stem = segment[: len(segment) - len(fugen)]
            if len(stem) < MIN_PART or not segment.endswith(fugen) or stem not in _LEXICON:
                continue
            rest: _Plan | None = (0, 0, ()) if end == len(word) else _best(word, end)
            if rest is None:
                continue
            plan = (1 + rest[0], len(fugen) + rest[1], (stem, *rest[2]))
            if best is None or plan < best:
                best = plan
    return best


@lru_cache(maxsize=65536)
def _split(word: str) -> tuple[str, ...]:
    plan = _best(word, 0)
    if plan is None or len(plan[2]) < 2:
        return (word,)
    return plan[2]


def split(word: str) -> list[str]:
    """Split a German compound into its lowercase parts, or return ``[word.lower()]``.

    Only words of 10 to 60 letters that the lexicon covers completely are split; linking
    elements are dropped from the parts. Spelling is kept: "Kuendigung" yields "kuendigung".

    Args:
        word: One token (any case).

    Returns:
        The parts in order; the lowercase word itself if it is short, unknown or not a compound.

    Examples:
        >>> split("Kündigungsschutzgesetz")
        ['kündigung', 'schutz', 'gesetz']
        >>> split("Arbeitszeitgesetz")
        ['arbeit', 'zeit', 'gesetz']
        >>> split("Gesetz")
        ['gesetz']
    """
    lowered = word.lower()
    if not MIN_WORD <= len(lowered) <= MAX_WORD or not lowered.isalpha():
        return [lowered]
    return list(_split(lowered))
