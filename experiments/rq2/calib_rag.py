"""GermanRAG-derived sets: ``faithfulness_constructed`` and ``refusal`` (T5.3 sets 2 and 4).

GermanRAG is CC BY-SA 4.0 (T2.1, ``DATA_LICENSES.md`` §7), so both sets use GermanRAG material
only (its passages already include the GermanDPR hard negatives) and go to config
``germanrag_derived``, never mixed with another config.
"""

from collections.abc import Sequence

import numpy as np
from rq2.calib_schema import CalibrationItem, make_item_id
from rq2.calib_sources import RagRow, article_of, context_id
from rq2.calib_split import balance, round_robin_sample, seeded_order
from rq2.construct import (
    HEDGES,
    REFUSALS,
    hedge,
    negate,
    split_sentences,
    swap_first_number,
    tokens,
)
from rq2.construct_checks import content_tokens, may_support, negation_ok

N_FAITH_ROWS = 300
N_REFUSAL_ROWS = 150


def _faith_item(
    row: RagRow, *, kontext: str, antwort: str, label: int, construction: str, hard: bool = False
) -> CalibrationItem:
    inputs = {"frage": row.question, "kontext": kontext, "antwort": antwort}
    cluster = context_id(row.positive_context)
    return CalibrationItem(
        item_id=make_item_id("faithfulness_constructed", cluster, construction, inputs),
        metric="faithfulness",
        cluster_id=cluster,
        inputs=inputs,
        label=label,
        source="germanrag",
        construction=construction,
        hard_negative=hard,
        hard_type=construction if hard else None,
    )


def _foreign_sentence(row: RagRow, pool: Sequence[RagRow], rng: np.random.Generator) -> str | None:
    """Return a sentence of a positive passage of a different article."""
    own = article_of(row.positive_context)
    others = [r for r in pool if article_of(r.positive_context) != own]
    if not others:
        return None
    sentences = split_sentences(others[int(rng.integers(len(others)))].positive_context)
    return sentences[int(rng.integers(len(sentences)))] if sentences else None


def faith_hard(
    row: RagRow, pool: Sequence[RagRow], rng: np.random.Generator
) -> list[CalibrationItem]:
    """The constructed hard negatives of one row, all on the positive passage."""
    ctx, ans = row.positive_context, row.answer
    out: list[CalibrationItem] = []
    swapped = swap_first_number(ans)
    new_tokens = set(tokens(swapped or "")) - set(tokens(ans))
    if swapped is not None and not (new_tokens & set(tokens(ctx))):
        out.append(
            _faith_item(
                row,
                kontext=ctx,
                antwort=swapped,
                label=0,
                construction="number_date_swap",
                hard=True,
            )
        )
    flipped = negate(ans)
    if flipped is not None and negation_ok(ans, flipped):
        out.append(
            _faith_item(
                row, kontext=ctx, antwort=flipped, label=0, construction="negation_flip", hard=True
            )
        )
    extra = _foreign_sentence(row, pool, rng)
    if extra is not None:
        out.append(
            _faith_item(
                row,
                kontext=ctx,
                antwort=f"{ans} {extra}",
                label=1,
                construction="partial_answer",
                hard=True,
            )
        )
    return out


def distractor_ok(row: RagRow, passage: str) -> bool:
    """True iff ``passage`` can serve as an unsupporting context for the row's answer.

    Rejected (D864, reviews of #107): passages from the positive passage's article, passages
    whose article title shares a word with the answer, and passages that may support the answer
    (``construct_checks.may_support``).
    """
    title = article_of(passage)
    if title == article_of(row.positive_context):
        return False
    title_words = {t for t in tokens(title.replace("_", " ")) if len(t) >= 3}
    if title_words & content_tokens(row.answer):
        return False
    return not may_support(row.answer, passage)


UNRELATED_TRIES = 20


def _unsupported(
    row: RagRow, pool: Sequence[RagRow], rng: np.random.Generator
) -> CalibrationItem | None:
    """The same answer on a passage that cannot support it.

    First a GermanRAG distractor of the row (``unsupported_context``); when every distractor is
    rejected by :func:`distractor_ok`, the positive passage of another sampled row that passes it
    (``unrelated_context``, at most :data:`UNRELATED_TRIES` seeded tries; D864).
    """
    negs = [c for i, c in enumerate(row.contexts) if i != row.positive and distractor_ok(row, c)]
    if negs:
        ctx, kind = negs[int(rng.integers(len(negs)))], "unsupported_context"
    else:
        tries = seeded_order(pool, rng)[:UNRELATED_TRIES]
        found = [o.positive_context for o in tries if distractor_ok(row, o.positive_context)]
        if not found:
            return None
        ctx, kind = found[0], "unrelated_context"
    return _faith_item(row, kontext=ctx, antwort=row.answer, label=0, construction=kind)


def build_faithfulness_constructed(rows: Sequence[RagRow], seed: int) -> list[CalibrationItem]:
    """Build ``faithfulness_constructed`` from answerable rows with a distractor passage.

    Args:
        rows: All GermanRAG rows.
        seed: Seed of the 300-row sample and every edit choice.

    Returns:
        50 / 50 positives and negatives (hard negatives first, D861).
    """
    rng = np.random.default_rng(seed)
    usable = [r for r in rows if r.answerable and len(r.contexts) >= 2]
    sample = round_robin_sample(usable, lambda r: article_of(r.positive_context), N_FAITH_ROWS, rng)
    pos: list[CalibrationItem] = []
    hard: list[CalibrationItem] = []
    other: list[CalibrationItem] = []
    for row in sample:
        pos.append(
            _faith_item(
                row,
                kontext=row.positive_context,
                antwort=row.answer,
                label=2,
                construction="gold_context",
            )
        )
        hard.extend(faith_hard(row, sample, rng))
        off = _unsupported(row, sample, rng)
        if off is not None:
            other.append(off)
    return balance(pos, hard, other, rng)


def _refusal_item(row: RagRow, *, antwort: str, label: int, construction: str) -> CalibrationItem:
    inputs = {"frage": row.question, "antwort": antwort}
    cluster = context_id(row.positive_context or row.contexts[0])
    hard = construction == "hedged_answer"
    return CalibrationItem(
        item_id=make_item_id("refusal", cluster, construction, inputs),
        metric="refusal_judged",
        cluster_id=cluster,
        inputs=inputs,
        label=label,
        source="germanrag",
        construction=construction,
        hard_negative=hard,
        hard_type="hedged_answer" if hard else None,
    )


def build_refusal(
    rows: Sequence[RagRow], seed: int, n: int = N_REFUSAL_ROWS
) -> list[CalibrationItem]:
    """Build the ``refusal`` set: label 1 = the answer is a refusal (W3.5, no ``erwartet``).

    ``n`` unanswerable rows give two different fixed paraphrases each (label 1); ``n`` answerable
    rows give the gold answer and a hedged gold answer (label 0, ``hedged_answer``).
    """
    rng = np.random.default_rng(seed)
    unans = seeded_order([r for r in rows if not r.answerable], rng)[:n]
    ans = seeded_order([r for r in rows if r.answerable], rng)[:n]
    out: list[CalibrationItem] = []
    for row in unans:
        for k in rng.choice(len(REFUSALS), size=2, replace=False):
            out.append(
                _refusal_item(
                    row,
                    antwort=REFUSALS[int(k)],
                    label=1,
                    construction=f"refusal_paraphrase_{int(k)}",
                )
            )
    for row in ans:
        out.append(_refusal_item(row, antwort=row.answer, label=0, construction="gold_answer"))
        hedged = hedge(row.answer, int(rng.integers(len(HEDGES))))
        out.append(_refusal_item(row, antwort=hedged, label=0, construction="hedged_answer"))
    return out
