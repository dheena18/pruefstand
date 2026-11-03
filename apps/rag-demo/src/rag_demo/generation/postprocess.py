"""Pure answer post-processing: ``<think>`` strip, output guard, citations, refusal (T3.6)."""

import re

from rag_demo.models import RagConfig

REFUSAL = "Die Dokumente enthalten dazu keine Information."
REFUSAL_EN = "The documents do not contain this information."
_THINK = re.compile(r"\A\s*<think>.*?</think>\s*", re.DOTALL)
_CITATION = re.compile(
    r"(?:§§?\s?\d+[a-z]?(?:\s+Abs\.\s?\d+)?(?:\s+(?:S\.|Satz)\s?\d+)?(?:\s+Nr\.\s?\d+)?"
    r"|Art(?:\.|ikel|icle)\s?\d+(?:\s+Abs\.\s?\d+)?)\s+[A-ZÄÖÜ][A-Za-zÄÖÜäöüß]{1,}"
)
_LEADING_QUOTES = re.compile(r"\A[\s\"'„“”«»]+")
_ENGLISH_WORDS = frozenset(
    [
        "the",
        "of",
        "is",
        "are",
        "what",
        "which",
        "how",
        "does",
        "do",
        "may",
        "can",
        "under",
        "when",
        "who",
        "for",
        "with",
        "and",
        "to",
        "in",
        "a",
        "an",
    ]
)
_GERMAN_WORDS = frozenset(
    [
        "der",
        "die",
        "das",
        "ist",
        "sind",
        "was",
        "welche",
        "wie",
        "wer",
        "wann",
        "darf",
        "kann",
        "nach",
        "bei",
        "für",
        "und",
        "zu",
        "in",
        "ein",
        "eine",
        "gilt",
        "muss",
        "wird",
        "hat",
    ]
)
_NGRAM = 8


def strip_think(text: str) -> tuple[str, int]:
    """Remove a leading ``<think>…</think>`` block; return the text and how many were removed."""
    stripped, count = _THINK.subn("", text, count=1)
    return stripped.strip(), count


def _words(text: str) -> list[str]:
    return re.findall(r"\w+", text.casefold())


def apply_output_guard(answer: str, system_prompt: str, cfg: RagConfig) -> str:
    """Refuse an answer that shares an 8-gram of words with the system prompt (prompt leak).

    With ``system_prompt_guard: off`` the answer passes unchanged.
    """
    if cfg.system_prompt_guard == "off":
        return answer
    prompt_words = _words(system_prompt)
    grams = {tuple(prompt_words[i : i + _NGRAM]) for i in range(len(prompt_words) - _NGRAM + 1)}
    words = _words(answer)
    if any(tuple(words[i : i + _NGRAM]) in grams for i in range(len(words) - _NGRAM + 1)):
        return REFUSAL
    return answer


def extract_citations(text: str) -> list[str]:
    """Return the distinct norm citations (§, Art., Article) in ``text`` in order of appearance.

    Examples:
        >>> extract_citations("Siehe § 622 Abs. 2 BGB.")
        ['§ 622 Abs. 2 BGB']
        >>> extract_citations("Article 6 GDPR and Art. 6 Abs. 1 DSGVO")
        ['Article 6 GDPR', 'Art. 6 Abs. 1 DSGVO']
    """
    return list(dict.fromkeys(m.group(0) for m in _CITATION.finditer(text)))


def is_refusal(answer: str) -> bool:
    """True when the answer starts with the canonical refusal sentence (DE or its EN twin).

    Leading quotes and case are ignored; the sentence may be followed by more text.

    Examples:
        >>> is_refusal("Die Dokumente enthalten dazu keine Information.")
        True
        >>> is_refusal("„The documents do not contain this information.“")
        True
        >>> is_refusal("Einen Monat (§ 622 BGB).")
        False
    """
    head = _LEADING_QUOTES.sub("", answer).casefold()
    return head.startswith((REFUSAL.casefold(), REFUSAL_EN.casefold()))


def detect_language(question: str) -> str:
    """Tiny heuristic: ``"en"`` when English function words outnumber German ones, else ``"de"``.

    Examples:
        >>> detect_language("What notice period applies after two years?")
        'en'
        >>> detect_language("Welche Kündigungsfrist gilt nach zwei Jahren?")
        'de'
    """
    words = _words(question)
    english = sum(w in _ENGLISH_WORDS for w in words)
    german = sum(w in _GERMAN_WORDS for w in words)
    return "en" if english > german else "de"
