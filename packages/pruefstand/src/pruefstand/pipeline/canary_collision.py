"""Collision check for semantic canaries (T2.6, D724).

A semantic canary is a leak only if the model could not know it from anywhere else. A value that
also occurs in a public chunk (law, decision) or in another private document would turn a correct
answer into a false leak, so the build, the validator and the held-out builder test every canary
pattern against all text except the canary's own document.
"""

import json
import re
from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path

from pruefstand.attacks.canary import number_word
from pruefstand.core.models.attacks import Canary
from pruefstand.ingest.corpus_files import FILE_SUFFIX, iter_lines
from pruefstand.metrics.deterministic.normalise import contains_forbidden, security_normalise

_NUMBER = re.compile(r"\d[\d.]*")


def _prefilter(canary: Canary) -> tuple[str, ...]:
    """Cheap substrings of which one must occur before the full pattern is evaluated."""
    found = _NUMBER.search(canary.token)
    if found is None:
        return ()
    digits = found.group(0).replace(".", "")
    words = (number_word(int(digits)),) if 1 <= int(digits) <= 999 else ()
    return (digits, *words)


def public_collisions(canaries: Sequence[Canary], chunks: Iterable[tuple[str, str]]) -> list[str]:
    """Return the doc ids of semantic canaries whose pattern matches text of another document.

    Args:
        canaries: The registry (token canaries are ignored).
        chunks: ``(doc_id, text)`` of every chunk of the corpus, private ones included; a canary
            is not tested against its own document.

    Returns:
        Sorted doc ids with a collision (empty = distinctive).
    """
    semantic = [(c, _prefilter(c)) for c in canaries if c.kind == "semantic" and c.forbidden_answer]
    hit: set[str] = set()
    for doc_id, text in chunks:
        folded = (text if text.isascii() else security_normalise(text)).replace(".", "").casefold()
        for canary, needles in semantic:
            if canary.doc_id in hit or canary.doc_id == doc_id:
                continue
            if needles and not any(n in folded for n in needles):
                continue
            if canary.forbidden_answer and contains_forbidden(text, canary.forbidden_answer):
                hit.add(canary.doc_id)
    return sorted(hit)


def corpus_items(directory: Path) -> Iterator[tuple[str, str]]:
    """Yield ``(doc_id, text)`` of every chunk of a corpus version directory.

    Raises:
        DatasetError: A chunk file is unreadable (see ``iter_lines``).
    """
    for path in sorted(directory.glob(f"*{FILE_SUFFIX}")):
        for line in iter_lines(path):
            chunk = json.loads(line)
            yield str(chunk.get("doc_id", "")), str(chunk.get("text", ""))
