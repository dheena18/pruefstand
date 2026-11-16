"""Fixed-token sub-chunking at index time (T3.4b, D1300-range decision).

``split_rows`` cuts every corpus chunk into consecutive pieces of at most ``size`` tokens of the
embedded text (the citation key plus the piece), no overlap. A piece ends at the last sentence end
in the second half of its window when there is one, else it is cut hard. Sentence ends are not
guessed from every full stop: a stop after a German legal abbreviation ("Abs.", "Nr.", "S.",
"i.V.m.", ...) or after an ordinal ("am 15. eines Monats", list markers "1. wenn") is no end.

The citation key counts in the size budget (``index_text`` prepends it to every piece when it is
embedded) but is never part of the stored piece ``text``: the retrieved text, and so the
``evidence_recall`` containment test of RQ1, only ever sees the body of the piece.
"""

import re
from collections.abc import Callable, Sequence
from typing import Any

from rag_demo.errors import ConfigError
from rag_demo.index.corpus_reader import index_text
from rag_demo.models import ChunkingCfg

TokenCounter = Callable[[str], int]
MIN_BODY_TOKENS = 16

#: Abbreviations after which a full stop never ends a sentence (lower case, word before the stop).
ABBREVIATIONS = frozenset(
    {
        "abs", "satz", "s", "nr", "nrn", "art", "buchst", "lit", "var", "alt", "hs", "halbs", "rn",
        "ziff", "anm", "abschn", "kap", "bzw", "ggf", "vgl", "etc", "usw", "ca", "evtl", "inkl",
        "zzgl", "insb", "bspw", "sog", "gem", "ff", "f", "u.a", "d.h", "z.b", "i.v.m", "i.s.d",
        "i.s", "i.d.r", "i.d.f", "o.ä", "u.ä", "z.t", "v.a", "m.w.n", "a.f", "n.f", "e.v", "bgbl",
        "dr", "prof", "nr.", "ggü", "vorbem", "str", "tel", "bsp", "geb", "gez", "hrsg", "jh",
    }
)  # fmt: skip
LOOKBACK = 40  # characters before a stop that can belong to its abbreviation
_WORD_BEFORE = re.compile(r"([\wäöüÄÖÜß.]+)$")
_STOP = re.compile(r"[.!?](?=\s)")
_NEXT = re.compile(r"\s+(\S)")


def _is_sentence_end(text: str, stop: int) -> bool:
    """True iff the ``.``/``!``/``?`` at ``stop`` ends a sentence (see the module docstring)."""
    following = _NEXT.match(text, stop + 1)
    if following is None:  # end of the text
        return True
    if text[stop] != ".":
        return True
    before = _WORD_BEFORE.search(text, max(0, stop - LOOKBACK), stop)  # bounded: no quadratic scan
    word = before.group(1) if before else ""
    if word.lower().strip(".") in ABBREVIATIONS or word.lower() in ABBREVIATIONS:
        return False
    if re.fullmatch(r"\d+", word) and following.group(1).islower():
        return False  # an ordinal ("am 15. eines Monats") or a list marker ("1. wenn")
    return not following.group(1).islower() or "\n" in text[stop + 1 : following.start(1)]


def sentence_ends(text: str) -> list[int]:
    """Offsets just after every sentence-ending stop of ``text`` (German legal abbreviations aware).

    >>> t = "Nach § 1 Abs. 2 gilt dies. Das ist neu."
    >>> [t[:e] for e in sentence_ends(t)]
    ['Nach § 1 Abs. 2 gilt dies.', 'Nach § 1 Abs. 2 gilt dies. Das ist neu.']
    """
    return [m.end() for m in _STOP.finditer(text) if _is_sentence_end(text, m.start())] + (
        [len(text.rstrip())] if text.rstrip() and not _STOP.search(text[-1:]) else []
    )


def _largest_fit(text: str, start: int, budget: int, count: TokenCounter) -> int:
    """Largest end offset (at a word boundary) with ``count(text[start:end]) <= budget``."""
    bounds = [m.start() for m in re.finditer(r"\s+", text) if m.start() > start] + [len(text)]
    lo, hi, best = 0, len(bounds) - 1, -1
    while lo <= hi:
        mid = (lo + hi) // 2
        if count(text[start : bounds[mid]].strip()) <= budget:
            best, lo = mid, mid + 1
        else:
            hi = mid - 1
    if best >= 0:
        return bounds[best]
    lo, hi, cut = start + 1, len(text), start + 1  # one word longer than the budget: cut by chars
    while lo <= hi:
        mid = (lo + hi) // 2
        if count(text[start:mid]) <= budget:
            cut, lo = mid, mid + 1
        else:
            hi = mid - 1
    return cut


def _back_off_abbreviation(text: str, start: int, end: int) -> int:
    """Move a hard cut back before a trailing abbreviation or ``§`` (it starts the next piece)."""
    while True:
        words = list(re.finditer(r"\S+", text[start:end]))
        if len(words) < 2:
            return end
        last = words[-1].group()
        key = last.lower().rstrip(".")
        if last == "§" or (last.endswith(".") and (key in ABBREVIATIONS or key.isdigit())):
            end = start + words[-2].end()
        else:
            return end


def split_text(text: str, budget: int, count: TokenCounter) -> list[str]:
    """Cut ``text`` into consecutive pieces of at most ``budget`` tokens, no overlap.

    A piece ends at the last sentence end in the second half of its window (measured in
    characters), else at the last word boundary that fits (hard cut).

    >>> split_text("Eins zwei drei. Vier fünf sechs. Sieben acht.", 7, lambda t: len(t.split()))
    ['Eins zwei drei. Vier fünf sechs.', 'Sieben acht.']
    """
    ends = sentence_ends(text)
    pieces: list[str] = []
    start = 0
    while start < len(text):
        while start < len(text) and text[start].isspace():
            start += 1
        if start >= len(text):
            break
        end = _largest_fit(text, start, budget, count)
        if end < len(text):
            half = start + (end - start) / 2
            inside = [e for e in ends if half <= e <= end and e > start]
            end = inside[-1] if inside else _back_off_abbreviation(text, start, end)
        pieces.append(text[start:end].strip())
        start = end
    return [p for p in pieces if p]


def split_rows(
    rows: Sequence[dict[str, Any]], cfg: ChunkingCfg, count: TokenCounter
) -> list[dict[str, Any]]:
    """Apply ``cfg`` to the corpus rows; ``per_section`` returns them unchanged.

    A row whose embedded text fits in ``cfg.size`` keeps its ``chunk_id``; a longer one becomes
    pieces with ids ``<chunk_id>#p<n>``, the same ``doc_id``, tenant, citation key, language and
    section, and the body of the piece as ``text`` (never the citation key).

    Raises:
        ConfigError: The citation key alone leaves fewer than ``MIN_BODY_TOKENS`` tokens.
    """
    if cfg.strategy == "per_section" or cfg.size is None:
        return list(rows)
    out: list[dict[str, Any]] = []
    for row in rows:
        if count(index_text(row)) <= cfg.size:
            out.append(row)
            continue
        key = row.get("citation_key")
        budget = cfg.size - (count(f"{key}\n") if key else 0)
        if budget < MIN_BODY_TOKENS:
            msg = f"chunking size {cfg.size} leaves no room after the citation key of {row['chunk_id']}"  # noqa: E501
            raise ConfigError(msg)
        pieces = split_text(str(row["text"]), budget, count)
        out.extend(
            {**row, "chunk_id": f"{row['chunk_id']}#p{n}", "text": body}
            for n, body in enumerate(pieces)
        )
    return out
