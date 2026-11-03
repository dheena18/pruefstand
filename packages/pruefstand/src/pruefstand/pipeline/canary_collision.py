"""Public-text collision check for semantic canaries (T2.6, D724).

A semantic canary is a leak only if the model could not know it from public text. A value that
also occurs in a public chunk (law, decision) would turn a correct answer into a false leak, so
the build and the validator test every canary pattern against all non-private chunks.
"""

import re
from collections.abc import Iterable, Sequence

from pruefstand.attacks.canary import number_word
from pruefstand.core.models.attacks import Canary
from pruefstand.metrics.deterministic.normalise import contains_forbidden

_NUMBER = re.compile(r"\d[\d.]*")


def _prefilter(canary: Canary) -> tuple[str, ...]:
    """Cheap substrings of which one must occur before the full pattern is evaluated."""
    found = _NUMBER.search(canary.token)
    if found is None:
        return ()
    digits = found.group(0).replace(".", "")
    words = (number_word(int(digits)),) if 1 <= int(digits) <= 999 else ()
    return (digits, *words)


def public_collisions(canaries: Sequence[Canary], texts: Iterable[str]) -> list[str]:
    """Return the doc ids of semantic canaries whose pattern matches any public text.

    Args:
        canaries: The registry (token canaries are ignored).
        texts: Text of every non-private chunk.

    Returns:
        Sorted doc ids with a collision (empty = distinctive).
    """
    semantic = [(c, _prefilter(c)) for c in canaries if c.kind == "semantic" and c.forbidden_answer]
    hit: set[str] = set()
    for text in texts:
        folded = text.replace(".", "").casefold()
        for canary, needles in semantic:
            if canary.doc_id in hit or (needles and not any(n in folded for n in needles)):
                continue
            if canary.forbidden_answer and contains_forbidden(text, canary.forbidden_answer):
                hit.add(canary.doc_id)
    return sorted(hit)
