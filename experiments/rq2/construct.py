"""Deterministic text edits that make calibration items true by construction (T5.3 S3).

No function here calls a model. Every random choice takes a ``numpy.random.Generator`` or a seed.
"""

import re
import unicodedata
from collections.abc import Sequence

import numpy as np

NUMBER_WORDS: tuple[str, ...] = (
    "eins",
    "zwei",
    "drei",
    "vier",
    "fünf",
    "sechs",
    "sieben",
    "acht",
    "neun",
    "zehn",
    "elf",
    "zwölf",
    "dreizehn",
)
MONTHS = "Januar|Februar|März|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember"
FINITE_VERBS: tuple[str, ...] = (
    "ist", "sind", "war", "waren", "wird", "wurde", "hat", "haben", "kann", "muss", "darf",
)  # fmt: skip

#: Fixed refusal paraphrases (W3.5). Exactly two of them are on T1.5b's phrase list
#: (``metrics/data/refusal_phrases.txt``): the first and the fourth.
REFUSALS: tuple[str, ...] = (
    "Die Dokumente enthalten dazu keine Information.",
    "Dazu lässt sich den Unterlagen nichts entnehmen.",
    "Darauf kann ich anhand der vorliegenden Texte nicht antworten.",
    "Ich kann diese Frage nicht beantworten.",
    "Die vorliegenden Quellen geben darüber keine Auskunft.",
    "Hierzu schweigen die bereitgestellten Texte, eine Antwort ist so nicht möglich.",
)
#: Hedge prefixes (W3.5). The colon keeps German word order and casing intact (D864).
HEDGES: tuple[str, ...] = ("Soweit ersichtlich: ", "Nach den Dokumenten gilt: ")
FRAMES: tuple[str, ...] = (
    "Die Antwort lautet: {a}.",
    "Laut dem Text: {a}.",
    "{a}, so steht es im Abschnitt.",
    "Es handelt sich um {a}.",
)
#: Function words that never make a span on their own (``same_paragraph_span``).
STOPWORDS = frozenset(
    [
        "der",
        "die",
        "das",
        "den",
        "dem",
        "des",
        "ein",
        "eine",
        "einen",
        "einem",
        "einer",
        "und",
        "oder",
        "in",
        "im",
        "am",
        "an",
        "auf",
        "aus",
        "bei",
        "mit",
        "nach",
        "von",
        "vom",
        "zu",
        "zum",
        "zur",
        "für",
        "über",
        "unter",
        "als",
        "wie",
        "es",
        "er",
        "sie",
        "ist",
        "sind",
        "war",
        "wurde",
        "wird",
        "hat",
        "haben",
        "nicht",
        "auch",
        "sich",
        "so",
        "da",
        "dass",
    ]
)
_TOKEN = re.compile(r"\w+")
_DIGITS = re.compile(r"\d+")
_WORD_NUM = re.compile(r"\b(" + "|".join(NUMBER_WORDS[:-1]) + r")\b", re.IGNORECASE)
_DATE_DAY = re.compile(r"\d{1,2}\.\s?(?:" + MONTHS + r")\b")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-ZÄÖÜ„\"(])")


def norm(text: str) -> str:
    """Return ``text`` NFC-normalised, case-folded and whitespace-collapsed."""
    return " ".join(unicodedata.normalize("NFC", text).casefold().split())


def tokens(text: str) -> list[str]:
    """Return the normalised word tokens of ``text``."""
    return _TOKEN.findall(norm(text))


def token_jaccard(a: str, b: str) -> float:
    """Return the Jaccard index of the token sets of ``a`` and ``b`` (0.0 if both are empty)."""
    sa, sb = set(tokens(a)), set(tokens(b))
    union = sa | sb
    return len(sa & sb) / len(union) if union else 0.0


def contains_either(a: str, b: str) -> bool:
    """Return True iff one normalised text is a substring of the other."""
    na, nb = norm(a), norm(b)
    return na in nb or nb in na


def _swap_digits(match: re.Match[str], text: str) -> str:
    raw = match.group()
    value = int(raw)
    is_day = _DATE_DAY.match(text, match.start()) is not None
    if is_day:
        new = value + 1 if value < 28 else value - 1  # keep a valid day
    else:
        new = value + 1 if len(str(value + 1)) == len(str(value)) else value - 1
    return str(new).zfill(len(raw))


def _swap_word(word: str) -> str:
    nxt = NUMBER_WORDS[NUMBER_WORDS.index(word.lower()) + 1]
    return nxt.capitalize() if word[0].isupper() else nxt


def swap_first_number(text: str) -> str | None:
    """Change exactly the first number of ``text``.

    Digits ``n -> n + 1`` keeping the digit count (else ``n - 1``); a day before a month name stays
    a valid day (``28 -> 27``, else ``+ 1``); German number words ``eins .. zwölf`` move to the next
    word, keeping the capitalisation.

    Returns:
        The edited text, or ``None`` when ``text`` has no number.
    """
    digit = _DIGITS.search(text)
    word = _WORD_NUM.search(text)
    if digit is not None and (word is None or digit.start() < word.start()):
        return text[: digit.start()] + _swap_digits(digit, text) + text[digit.end() :]
    if word is not None:
        return text[: word.start()] + _swap_word(word.group()) + text[word.end() :]
    return None


def negate(text: str) -> str | None:
    """Flip the polarity of ``text``.

    Removes the first ``nicht`` (``kein*`` becomes ``ein*``); otherwise inserts ``nicht`` after the
    first finite verb of :data:`FINITE_VERBS`.

    Returns:
        The edited text, or ``None`` when there is neither a negation nor a listed verb.
    """
    nicht = re.search(r"\s?\bnicht\b", text)
    kein = re.search(r"\b([Kk])ein(e[nmrs]?)?\b", text)
    if nicht and (kein is None or nicht.start() < kein.start()):
        return text[: nicht.start()] + text[nicht.end() :]
    if kein:
        repl = ("E" if kein.group(1) == "K" else "e") + "in" + (kein.group(2) or "")
        return text[: kein.start()] + repl + text[kein.end() :]
    verb = re.search(r"\b(" + "|".join(FINITE_VERBS) + r")\b", text)
    if verb is None:
        return None
    return text[: verb.end()] + " nicht" + text[verb.end() :]


def partial(text: str) -> str | None:
    """Return a partially correct version of ``text``.

    The first conjunct of an ``A und B`` text; otherwise the first half of the tokens of a text
    with at least six tokens, cut at a word boundary.

    Returns:
        The partial text, or ``None`` for a short text without ``und``.
    """
    stripped = text.strip().rstrip(".")
    if " und " in stripped:
        first = stripped.split(" und ", 1)[0].strip(" ,")
        if first and norm(first) != norm(stripped):
            return first
    words = stripped.split()
    if len(words) >= 6:  # rule of the prompt
        return " ".join(words[: len(words) // 2])
    return None


def frame(answer: str, seed: int) -> str:
    """Wrap ``answer`` in one of the four :data:`FRAMES`, chosen by ``seed``."""
    template = FRAMES[int(np.random.default_rng(seed).integers(len(FRAMES)))]
    return template.format(a=answer.strip().rstrip("."))


def hedge(answer: str, index: int) -> str:
    """Prefix ``answer`` with :data:`HEDGES` ``[index]``."""
    return HEDGES[index] + answer.strip()


def split_sentences(text: str) -> list[str]:
    """Split ``text`` into sentences; heading lines (``== x ==``) and the title line are dropped."""
    out: list[str] = []
    for raw in text.split("\n"):
        line = raw.strip()
        if not line or line.startswith("=") or " " not in line:
            continue
        out.extend(s.strip() for s in _SENTENCE_END.split(line) if s.strip())
    return out


def _free_sentences(context: str, answers: Sequence[tuple[str, int]]) -> list[str]:
    spans = [(start, start + len(t)) for t, start in answers if start >= 0]
    free: list[str] = []
    for sent in split_sentences(context):
        pos = context.find(sent)
        hit = any(pos < end and start < pos + len(sent) for start, end in spans)
        if not hit and not any(contains_either(sent, t) for t, _ in answers):
            free.append(sent)
    return free


def same_paragraph_span(
    context: str, answers: Sequence[tuple[str, int]], reference: str, rng: np.random.Generator
) -> str | None:
    """Return a wrong answer of the reference's length from the same paragraph.

    Takes the sentences of ``context`` that overlap no annotator answer span and neither contain
    nor are contained in any answer; picks, seeded, one of their windows of as many words as the
    reference (a whole sentence when it is shorter) that starts and ends on a content word.

    Args:
        context: The GermanQuAD paragraph.
        answers: ``(text, answer_start)`` of every annotator answer.
        reference: The reference answer (sets the length).
        rng: Seeded generator.

    Returns:
        The span, or ``None`` when no such window exists.
    """
    free = _free_sentences(context, answers)
    n = max(1, len(reference.split()))
    windows = [w for sent in free for w in _windows(sent, n)]
    windows = [w for w in windows if not any(contains_either(w, t) for t, _ in answers)]
    return windows[int(rng.integers(len(windows)))] if windows else None


def _windows(sentence: str, n: int) -> list[str]:
    """Return the ``n``-word windows of ``sentence`` that start and end on a content word."""
    words = sentence.rstrip(".").split()
    if len(words) <= n:
        return [" ".join(words)]
    out: list[str] = []
    for i in range(len(words) - n + 1):
        span = " ".join(words[i : i + n]).strip(" ,;:()")
        edge = tokens(span)
        if edge and edge[0] not in STOPWORDS and edge[-1] not in STOPWORDS:
            out.append(span)
    return out
