"""Text rules of the QA filters (T4.3): the copy rules and the "der Text" rule, enforced.

The generation prompts only ASK the model not to copy chunk text and not to refer to "the text";
``check_overlap`` is where these rules are enforced (D781). Texts are compared as words: NFC,
lower case, soft hyphens removed, every run of non-word characters is one separator, so
``Kündigungsfrist`` typed with a combining diaeresis equals the precomposed spelling and
punctuation never hides a copy.
"""

import re
import unicodedata
from collections.abc import Sequence

from pruefstand.core.enums import Lang
from pruefstand.core.errors import ConfigError
from pruefstand.core.models.corpus import Chunk
from pruefstand.core.models.dataset import FilterResult, QACandidate

NGRAM = 6
_SOFT_HYPHEN = "­"
_WORD = re.compile(r"\w+")
_SOURCE_NOUN = (
    r"(?:text(?:es|s)?|textauszug|abschnitt(?:s|es)?|auszug(?:s|es)?|ausschnitt|passage"
    r"|paragra(?:f|ph)(?:en|s)?|vorschrift(?:en)?|norm)"
)
_TEXT_NOUN = r"(?:text(?:es|s)?|textauszug|abschnitt(?:s|es)?|auszug(?:s|es)?|ausschnitt|passage)"
_POINTER = (
    r"(?:dies(?:e|er|em|en|es)|vorliegend\w*|zitiert\w*|genannt\w*|obig\w*|angegeben\w*"
    r"|folgend\w*|oben\s+genannt\w*)"
)
# a pointer word + text/norm noun always refers to the given source; a bare article + text noun
# does too unless a genitive/of-phrase turns it into an ordinary subject ("Text eines Vertrags")
_META_DE = (
    re.compile(rf"\b{_POINTER}\s+{_SOURCE_NOUN}\b"),
    re.compile(
        rf"\b(?:der|dem|den|des|im|laut|gemäß|vom)\s+{_TEXT_NOUN}\b(?!\s+(?:eines|einer|einem|von)\b)"
    ),
)
_META_EN = re.compile(r"\b(?:the|this|that)\s+(?:text|passage|excerpt|extract)\b")
_NORM_REF = re.compile(
    r"(?:§§?|\b(?:Artikel|Art|Absatz|Abs|Satz|S|Nr|Nummer|Buchstabe|lit)\b\.?)\s*\d+[a-z]?(?![a-z])",
    re.IGNORECASE,
)
_LAWS = (
    "BGB|KSchG|ArbZG|DSGVO|BDSG|ZPO|StGB|StPO|HGB|BetrVG|MuSchG|BUrlG|TzBfG|EntgFG|AGG|GG|SGB|UrhG"
    "|UStG|EStG|VVG|VAG|GmbHG|AktG|InsO|WEG|GVG|TTDSG|AO|ArbSchG|NachwG|MiLoG|BEEG|SGG|VwGO"
)
_LAW_NAME = re.compile(
    rf"\b(?:Bürgerliche[nms]?\s+Gesetzbuch\w*|[A-ZÄÖÜ][A-Za-zÄÖÜäöü-]*(?:gesetz|gesetzbuch|verordnung)\w*"
    rf"|(?:{_LAWS}))\b"
)
_FOLD = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})


def words(text: str) -> list[str]:
    r"""Split ``text`` into normalised words (NFC, lower case, no soft hyphens, no punctuation).

    Examples:
        >>> words("Kündigungsfrist: vier Wochen, zum 15.")
        ['kündigungsfrist', 'vier', 'wochen', 'zum', '15']
        >>> words("Ku\u0308ndigung") == words("K\u00fcndigung")
        True
    """
    normal = unicodedata.normalize("NFC", text).replace(_SOFT_HYPHEN, "").lower()
    return _WORD.findall(normal)


def copy_words(text: str) -> list[str]:
    """Words for the copy rules: ``words`` without norm references, with umlauts folded.

    ``§ 622``, ``Abs. 2``, ``Satz 1``, ``Art. 5`` and law names (``BGB``, ``Bürgerlichen
    Gesetzbuchs``, ``Kündigungsschutzgesetz``) are not copying; ``ä ö ü ß`` become ``ae oe ue
    ss``, so ``Kuendigungsfrist`` equals ``Kündigungsfrist``.

    Examples:
        >>> copy_words("Wann gilt § 622 Abs. 2 Satz 1 BGB für Kündigungen?")
        ['wann', 'gilt', 'fuer', 'kuendigungen']
        >>> copy_words("Straße") == copy_words("Strasse")
        True
    """
    plain = unicodedata.normalize("NFC", text).replace(_SOFT_HYPHEN, "")
    plain = _LAW_NAME.sub(" ", _NORM_REF.sub(" ", plain))
    return _WORD.findall(plain.lower().translate(_FOLD))


def ngrams(tokens: Sequence[str], n: int = NGRAM) -> set[tuple[str, ...]]:
    """Return the word n-grams of ``tokens`` (empty when there are fewer than ``n`` words).

    Examples:
        >>> sorted(ngrams(["a", "b", "c"], 2))
        [('a', 'b'), ('b', 'c')]
    """
    return {tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}


def overlap_ratio(question: Sequence[str], chunk: Sequence[str], n: int = NGRAM) -> float:
    """Share of the question's word n-grams that also occur in the chunk, in [0, 1].

    A question with fewer than ``n`` words has no n-gram and cannot copy one: 0.0.

    Examples:
        >>> overlap_ratio("a b c d".split(), "x a b c y".split(), 3)
        0.5
        >>> overlap_ratio("a b".split(), "a b c".split(), 3)
        0.0
    """
    own = ngrams(question, n)
    if not own:
        return 0.0
    return len(own & ngrams(chunk, n)) / len(own)


def longest_common_run(a: Sequence[str], b: Sequence[str]) -> int:
    """Length (in words) of the longest run of words that both sequences contain.

    Examples:
        >>> longest_common_run("das ist die frist".split(), "ja das ist die norm".split())
        3
    """
    best = 0
    row = [0] * (len(b) + 1)
    for x in a:
        nxt = [0] * (len(b) + 1)
        for j, y in enumerate(b, start=1):
            if x == y:
                nxt[j] = row[j - 1] + 1
                best = max(best, nxt[j])
        row = nxt
    return best


def refers_to_text(question: str, lang: Lang = Lang.DE) -> bool:
    """True when the question talks about "the text" it was written from (prompt rule).

    Examples:
        >>> refers_to_text("Was sagt der Text zur Kündigungsfrist?")
        True
        >>> refers_to_text("Wie lange ist die Kündigungsfrist?")
        False
        >>> refers_to_text("Was regelt die vorliegende Vorschrift?")
        True
        >>> refers_to_text("Was ist der Text eines Arbeitsvertrags?")
        False
        >>> refers_to_text("What does the passage say?", Lang.EN)
        True
    """
    normal = unicodedata.normalize("NFC", question).lower()
    patterns = (_META_EN,) if lang is Lang.EN else _META_DE
    return any(p.search(normal) for p in patterns)


def check_overlap(
    c: QACandidate,
    chunk: Chunk,
    max_ngram_overlap: float,
    *,
    long_copy_words: int = 8,
) -> FilterResult:
    """Reject a question that copies the chunk or talks about "the text".

    Rules (D790): the share of the question's word 6-grams that occur in the chunk must not exceed
    ``max_ngram_overlap`` (``ngram_overlap``; 0.0 = no shared 6-gram), no run of ``long_copy_words``
    words may be shared (``long_copy``), and the question must not refer to "der Text",
    "der Abschnitt", "der Auszug" (``meta_reference``). A pair is checked against each of its
    chunks by the caller.

    Args:
        c: The candidate.
        chunk: One source chunk of the candidate.
        max_ngram_overlap: Allowed share in [0, 1].
        long_copy_words: Length of a shared word run that counts as a copy.

    Returns:
        ``FilterResult(kept=True, reasons=())`` or the reasons found, in the order
        ``ngram_overlap``, ``long_copy``, ``meta_reference``.

    Raises:
        ConfigError: ``max_ngram_overlap`` is outside [0, 1] or ``long_copy_words`` < 2.

    Examples:
        >>> from pruefstand.core.models.corpus import Chunk
        >>> chunk = Chunk(
        ...     chunk_id="a#0", doc_id="a", tenant="t", lang="de", citation_key=None, section=None,
        ...     text="Das Arbeitsverhältnis kann mit einer Frist von vier Wochen gekündigt werden.",
        ...     parallel_id=None, version_date=None, license="l", source="gii:bgb",
        ... )
        >>> q = "Gilt eine Frist von vier Wochen gekündigt werden?"
        >>> cand = QACandidate(question=q, answer="a", citation=None, chunk_id="a#0",
        ...                    prompt_version="qa_factual_de_v1")
        >>> check_overlap(cand, chunk, 0.0).reasons
        ('ngram_overlap',)
    """
    if not 0.0 <= max_ngram_overlap <= 1.0:
        msg = f"max_ngram_overlap must be in [0, 1], not {max_ngram_overlap}"
        raise ConfigError(msg)
    if long_copy_words < 2:
        msg = f"long_copy_words must be at least 2, not {long_copy_words}"
        raise ConfigError(msg)
    question, source = copy_words(c.question), copy_words(chunk.text)
    reasons: list[str] = []
    if overlap_ratio(question, source) > max_ngram_overlap:
        reasons.append("ngram_overlap")
    if longest_common_run(question, source) >= long_copy_words:
        reasons.append("long_copy")
    if refers_to_text(c.question, c.lang):
        reasons.append("meta_reference")
    return FilterResult(kept=not reasons, reasons=tuple(reasons))
