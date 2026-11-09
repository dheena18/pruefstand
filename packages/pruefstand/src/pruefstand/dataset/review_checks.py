"""Deterministic checks that override the review model (T4.7a, SPEC §3.5 step 4).

The model reads the case and gives a verdict; these rules run on top and win:

* **citation exact**: every gold citation names the provision of a source chunk
  (``citation_mismatch`` otherwise, always a reject, whatever the model said);
* **the reference answer stays inside the source**: a number, paragraph or duration that the source
  does not state is a reject (`answer_fact_not_in_source`);
* **an unanswerable case is never fixed** (a new question could make it answerable);
* **a fix only touches the question**: the fixed question must pass the T4.3 copy rules
  (``fix_copies_source``), and a rewritten answer is allowed only for a reviewer that may rewrite
  references, and then only if it keeps every number, paragraph and duration of the original that
  the source text states (``fix_lost_fact``).
"""

import re
from collections.abc import Mapping, Sequence

from pruefstand.core.citations import extract_citations, parse_one
from pruefstand.core.enums import Category
from pruefstand.core.models.corpus import Chunk
from pruefstand.core.models.dataset import ModelVerdict, QACandidate, ReviewItem
from pruefstand.core.models.testcase import TestCase
from pruefstand.dataset.evidence import absatz_scope, normalise_text
from pruefstand.dataset.filters_text import check_overlap
from pruefstand.dataset.review import ATTACK_CATEGORIES, REWRITE_FORBIDDEN

CITATION_MISMATCH = "citation_mismatch"
CITATION_MISSING = "citation_missing"
CHUNK_MISSING = "chunk_missing"
FIX_COPIES_SOURCE = "fix_copies_source"
FIX_LOST_FACT = "fix_lost_fact"
FIX_UNCHANGED = "fix_unchanged"
FIX_UNANSWERABLE = "fix_unanswerable"
FIX_ADDS_QUESTION = "fix_adds_question"
ANSWER_FACT_NOT_IN_SOURCE = "answer_fact_not_in_source"
_INTERROGATIVE = re.compile(
    r"\b(?:wie|was|wann|wer|wen|wem|wo|woher|wohin|warum|wieso|weshalb|welche[rsmn]?|wodurch|womit)\b",
    re.IGNORECASE,
)
_WORD_VALUE = {
    "ein": 1, "eine": 1, "einen": 1, "einem": 1, "einer": 1, "zwei": 2, "drei": 3, "vier": 4,
    "fünf": 5, "sechs": 6, "sieben": 7, "acht": 8, "neun": 9, "zehn": 10, "elf": 11, "zwölf": 12,
    "dreizehn": 13, "vierzehn": 14, "fünfzehn": 15, "sechzehn": 16, "siebzehn": 17,
    "achtzehn": 18, "neunzehn": 19, "zwanzig": 20, "dreißig": 30,
}  # fmt: skip
_NUMBER = "|".join(sorted(_WORD_VALUE, key=len, reverse=True))
_UNIT = r"(?:Tag\w*|Woche\w*|Monat\w*|Jahr\w*|Stunde\w*|Minute\w*)"
_FACT = re.compile(
    rf"§\s*\d+\w*|\b(?:\d+|{_NUMBER})\s+{_UNIT}|\b\d+(?:[.,]\d+)?\b",
    re.IGNORECASE,
)
ANSWERABLE = frozenset(
    {Category.FACTUAL, Category.MULTI_HOP, Category.COMPARISON, Category.CROSS_LINGUAL}
)


def citation_matches(gold: str, key: str | None) -> bool:
    """Return whether the gold citation names the provision of a chunk's citation key.

    The chunk key is at section level (``§ 622 BGB``) or finer (``§ 622 Abs. 2 BGB``); the gold
    citation matches when kind, number and law agree and, where the chunk key names an Absatz, the
    Absatz too.

    Examples:
        >>> citation_matches("§ 622 Abs. 2 BGB", "§ 622 BGB")
        True
        >>> citation_matches("§ 622 Abs. 2 BGB", "§ 623 BGB")
        False
        >>> citation_matches("§ 622 Abs. 2 BGB", "§ 622 Abs. 3 BGB")
        False
    """
    parsed, chunk = parse_one(gold), parse_one(key or "")
    if parsed is None or chunk is None:
        return False
    if (parsed.kind, parsed.number, parsed.law) != (chunk.kind, chunk.number, chunk.law):
        return False
    return chunk.absatz is None or chunk.absatz == parsed.absatz


def source_chunks_of(case: TestCase, by_doc: Mapping[str, Sequence[Chunk]]) -> list[Chunk]:
    """Return the chunk of each gold document that carries the case's evidence.

    Per document the chunk holding ``evidence_span`` is preferred, then the first chunk whose
    citation key matches a gold citation, then the first chunk.
    """
    found: list[Chunk] = []
    for doc_id in case.gold_doc_ids:
        options = list(by_doc.get(doc_id, ()))
        if not options:
            continue
        span = case.evidence_span or ""
        by_span = [c for c in options if span and span in c.text]
        by_key = [
            c
            for c in options
            if any(citation_matches(g, c.citation_key) for g in case.gold_citations)
        ]
        found.append((by_span or by_key or options)[0])
    return found


def fact_keys(text: str, *, bare: bool = True) -> dict[str, str]:
    """Return ``{normalised fact: as written}`` for numbers, paragraphs and durations of ``text``.

    Digits and German number words are one form (``11 Stunden`` equals ``elf Stunden``, ``ein`` and
    ``einen`` are 1) and a unit is compared by its first four letters (``Jahren`` equals
    ``Jahre``). With ``bare`` a duration also yields its bare number, so ``acht Stunden`` knows
    ``8`` (used for the source, not for the answer).

    Examples:
        >>> sorted(fact_keys("Frist von zwei Jahren und 30 Minuten"))
        ['2', '2 jahr', '30', '30 minu']
        >>> "11 stun" in fact_keys("elf Stunden")
        True
    """
    keys: dict[str, str] = {}
    for m in _FACT.finditer(text):
        raw = m.group(0)
        words = raw.split()
        if raw.startswith("§"):
            keys.setdefault("".join(raw.split()).casefold(), raw)
        elif len(words) == 2:
            number = str(_WORD_VALUE.get(words[0].casefold(), words[0]))
            keys.setdefault(f"{number} {words[1].casefold()[:4]}", raw)
            if bare:
                keys.setdefault(number, raw)
        else:
            keys.setdefault(raw.replace(",", ".").casefold(), raw)
    return keys


def unsupported_facts(answer: str, source_text: str) -> list[str]:
    """Return the numbers, paragraphs and durations of ``answer`` that ``source_text`` lacks.

    ``source_text`` is the source chunks plus whatever else the answer may repeat (the question).

    Examples:
        >>> unsupported_facts("Drei Monate.", "Frist von zwei Wochen")
        ['Drei Monate']
        >>> unsupported_facts("Zwei Wochen.", "Frist von zwei Wochen")
        []
    """
    known = fact_keys(source_text)
    return [raw for key, raw in fact_keys(answer, bare=False).items() if key not in known]


def _cited_texts(case: TestCase, pool: Sequence[Chunk]) -> list[str]:
    """Return the text the answer may rely on: the cited Absatz of each chunk, else the chunk.

    A gold citation that names an Absatz limits its provision's chunks to that Absatz (a number from
    another Absatz of the same paragraph is not supported); without an Absatz the whole chunk
    counts.
    """
    absaetze: dict[tuple[str, str, str], set[str]] = {}
    for gold in case.gold_citations:
        for c in extract_citations(gold):
            absaetze.setdefault((c.kind, c.number, c.law), set())
            if c.absatz:
                absaetze[(c.kind, c.number, c.law)].add(c.absatz)
    texts: list[str] = []
    for chunk in pool:
        key = parse_one(chunk.citation_key or "")
        wanted = absaetze.get((key.kind, key.number, key.law), set()) if key else set()
        if not wanted:
            texts.append(chunk.text)
            continue
        scopes = (absatz_scope(normalise_text(chunk.text), a) for a in sorted(wanted))
        texts.extend(sc for sc in scopes if sc is not None)
    return texts


def deterministic_problems(
    case: TestCase, chunks: Sequence[Chunk], facts_from: Sequence[Chunk] | None = None
) -> tuple[str, ...]:
    """Return the deterministic findings of ``case`` against its source ``chunks``.

    Answerable cases need a source chunk and gold citations; each gold citation must match the key
    of one of the chunks (``citation_mismatch``), and every number, paragraph and duration of the
    reference answer must stand in the source or in the question (``answer_fact_not_in_source``).
    The facts are looked up in ``facts_from`` (default ``chunks``): pass every chunk of the gold
    documents, since the cited Absatz need not be in the chunk chosen for the citation. Other
    categories have no findings here.
    """
    if case.category not in ANSWERABLE:
        return ()
    if not chunks:
        return (CHUNK_MISSING,)
    if not case.gold_citations:
        return (CITATION_MISSING,)
    found: list[str] = []
    keys = [c.citation_key for c in chunks]
    if not all(any(citation_matches(g, k) for k in keys) for g in case.gold_citations):
        found.append(CITATION_MISMATCH)
    pool = facts_from if facts_from else chunks
    source = " ".join([case.question, *_cited_texts(case, pool), *(k for k in keys if k)])
    if unsupported_facts(case.reference_answer or "", source):
        found.append(ANSWER_FACT_NOT_IN_SOURCE)
    return tuple(found)


def lost_facts(original: str, fixed: str, source_text: str) -> list[str]:
    """Return the facts of ``original`` that ``fixed`` lost.

    Facts are numbers, paragraphs and durations of ``original`` that the source text states.

    Examples:
        >>> lost_facts("Er beträgt einen Monat.", "Er beträgt vier Wochen.", "Frist: einen Monat")
        ['einen Monat']
    """
    source, kept = fact_keys(source_text), fact_keys(fixed)
    return [
        raw
        for key, raw in fact_keys(original, bare=False).items()
        if key in source and key not in kept
    ]


def _question_problem(case: TestCase, fixed: str, chunks: Sequence[Chunk]) -> str | None:
    if fixed.strip() == case.question.strip():
        return FIX_UNCHANGED
    if len(_INTERROGATIVE.findall(fixed)) > len(_INTERROGATIVE.findall(case.question)):
        return FIX_ADDS_QUESTION  # a fix asks the same thing, not one more
    for chunk in chunks:
        probe = QACandidate(
            question=fixed,
            answer=case.reference_answer or "-",
            citation=None,
            chunk_id=chunk.chunk_id,
            prompt_version=case.generation_prompt_version or "none",
        )
        if not check_overlap(probe, chunk, 0.0).kept:
            return FIX_COPIES_SOURCE
    return None


def _fix_problems(
    case: TestCase, verdict: ModelVerdict, chunks: Sequence[Chunk], *, reject_only: bool
) -> tuple[str, ...]:
    if case.category is Category.UNANSWERABLE:
        return (FIX_UNANSWERABLE,)  # a new question could make the case answerable
    problems: list[str] = []
    if verdict.fixed_answer:
        if reject_only:
            return (REWRITE_FORBIDDEN,)
        text = " ".join(c.text for c in chunks)
        if lost_facts(case.reference_answer or "", verdict.fixed_answer, text):
            problems.append(FIX_LOST_FACT)
    if verdict.fixed_question:
        problem = _question_problem(case, verdict.fixed_question, chunks)
        if problem:
            problems.append(problem)
    elif not verdict.fixed_answer:
        problems.append("fix_without_text")
    return tuple(problems)


def finalise(
    case: TestCase,
    chunks: Sequence[Chunk],
    verdict: ModelVerdict,
    *,
    model: str,
    reject_only: bool = True,
    facts_from: Sequence[Chunk] | None = None,
) -> ReviewItem:
    """Combine the model verdict with the deterministic checks into the final ``ReviewItem``.

    Args:
        case: The reviewed case.
        chunks: Its source chunks (see ``source_chunks_of``).
        verdict: The model's verdict.
        model: Reviewer model id, recorded on the item.
        facts_from: Every chunk of the gold documents (the fact check looks there).
        reject_only: The reviewer must not rewrite references (ADR-0019): a ``fix`` with a
            ``fixed_answer`` is a reject (``reference_rewrite_forbidden``).

    Returns:
        The item: ``reject`` with the findings when a deterministic check fails, else the model
        verdict (a ``fix`` that fails its checks becomes a ``reject``).
    """
    found = deterministic_problems(case, chunks, facts_from)
    final = verdict.verdict
    if verdict.verdict == "fix":
        found = (*found, *_fix_problems(case, verdict, chunks, reject_only=reject_only))
    if found:
        final = "reject"
    keep_fix = final == "fix"
    return ReviewItem(
        case_id=case.id,
        cluster_id=case.cluster_id,
        category=case.category.value,
        prompt_version=case.generation_prompt_version or "none",
        split=case.split.value,
        verdict=final,
        reason=verdict.reason,
        reasons=found,
        fixed_question=verdict.fixed_question if keep_fix else None,
        fixed_answer=verdict.fixed_answer if keep_fix else None,
        model=model,
        model_verdict=verdict.verdict,
    )


def deterministic_item(
    case: TestCase, chunks: Sequence[Chunk], reason: str, facts_from: Sequence[Chunk] | None = None
) -> ReviewItem:
    """Return the item of a case that goes to no model (attack and probe cases, missing source)."""
    found = (
        deterministic_problems(case, chunks, facts_from)
        if case.category not in ATTACK_CATEGORIES
        else ()
    )
    return ReviewItem(
        case_id=case.id,
        cluster_id=case.cluster_id,
        category=case.category.value,
        prompt_version=case.generation_prompt_version or "none",
        split=case.split.value,
        verdict="reject" if found else "ok",
        reason=reason,
        reasons=found,
        model="deterministic",
    )
