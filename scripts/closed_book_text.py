"""Text helpers of ``closed_book.py``: content words, recall and negations (T4.7b S4)."""

import re
import unicodedata


def _words(text: str) -> frozenset[str]:
    return frozenset(text.split())


_STOPWORDS = _words(
    """einen eines einer einem eine sind wird werden wurde wurden oder auch sowie kann koennen
    können muss müssen mussen nach dass diese dieser dieses diesen jeweils durch unter über ueber
    gegen ohne sich dann wenn aber haben hat sein seine seiner zwischen bereits ferner dabei dafür
    that this with from have been will shall must also their there which when than into
    under over"""
)
_CITATION = re.compile(
    r"(?:§§?|Art\.?|Artikel)\s*\d+(?:[a-z]\b)?"
    r"(?:\s*(?:Abs\.|Absatz|S\.|Satz|Nr\.|Nummer|lit\.)\s*\w+)*"
    r"(?:\s+[A-ZÄÖÜ]{2,}[A-Za-zäöü]*)?"
)
_TOKEN = re.compile(r"[^\W_]+")
_NEGATION = re.compile(r"nicht|nichts|nie|niemals|niemand\w*|nirgends|nirgendwo|weder|kein\w*")
_MIN_WORD = 4
_ENDINGS = ("ern", "en", "em", "er", "es", "e", "n", "s")


def _stem(word: str) -> str:
    for ending in _ENDINGS:
        if word.endswith(ending) and len(word) - len(ending) >= _MIN_WORD:
            return word[: -len(ending)]
    return word


def content_words(text: str) -> frozenset[str]:
    """The content words of ``text``: citations removed, casefolded, stopwords dropped, stemmed.

    A content word is a number or a word of at least four letters that is not a stopword; a
    light German suffix strip (``Kalendermonats`` -> ``kalendermonat``) makes inflections match.

    Args:
        text: A reference or a model answer.

    Returns:
        The set of stems.

    Examples:
        >>> sorted(content_words("Einen Monat zum Ende eines Kalendermonats (§ 622 Abs. 2 BGB)."))
        ['ende', 'kalendermonat', 'monat']
    """
    plain = _CITATION.sub(" ", unicodedata.normalize("NFC", text)).casefold()
    words = _TOKEN.findall(plain)
    return frozenset(
        _stem(w) for w in words if (w.isdigit() or len(w) >= _MIN_WORD) and w not in _STOPWORDS
    )


def content_recall(reference: str, answer: str) -> float:
    """Share of the reference's content words found in the answer (0.0 when it has none).

    Args:
        reference: The reference answer.
        answer: The model answer.

    Returns:
        A value in ``[0, 1]``.

    Examples:
        >>> reference = "Einen Monat zum Ende eines Kalendermonats."
        >>> content_recall(reference, "Nach § 622 BGB einen Monat.")
        0.3333333333333333
    """
    wanted = content_words(reference)
    return len(wanted & content_words(answer)) / len(wanted) if wanted else 0.0


def negations(text: str) -> frozenset[str]:
    """The negation words of ``text``, casefolded, inflections folded (``keinen`` -> ``kein``).

    Examples:
        >>> sorted(negations("Keinem darf nicht gekündigt werden, niemandem auch nicht."))
        ['kein', 'nicht', 'niemand']
    """
    found = (w for w in _TOKEN.findall(text.casefold()) if _NEGATION.fullmatch(w))
    return frozenset(
        "kein" if w.startswith("kein") else "niemand" if w.startswith("niemand") else w
        for w in found
    )
