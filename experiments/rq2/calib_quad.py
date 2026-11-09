"""GermanQuAD-derived sets: ``correctness`` and ``consistency`` (T5.3 sets 3 and 5, CC BY 4.0)."""

from collections.abc import Sequence

import numpy as np
from rq2.calib_schema import CalibrationItem, make_item_id
from rq2.calib_sources import QuadRow
from rq2.calib_split import balance, round_robin_sample
from rq2.construct import (
    contains_either,
    frame,
    negate,
    norm,
    partial,
    same_paragraph_span,
    swap_first_number,
    token_jaccard,
)
from rq2.construct_checks import has_answer_content, negation_ok

N_QUESTIONS = 300
JACCARD_MAX = 0.3


def sample_questions(rows: Sequence[QuadRow], seed: int, n: int = N_QUESTIONS) -> list[QuadRow]:
    """Seeded sample of ``n`` questions with ≥ 2 annotator answers, spread over articles."""
    usable = [r for r in rows if len(r.answers) >= 2]
    return round_robin_sample(usable, lambda r: r.article, n, np.random.default_rng(seed))


def other_answer(row: QuadRow, pool: Sequence[QuadRow], rng: np.random.Generator) -> str | None:
    """Return an answer to another question of the same article that is far from ``row``'s.

    Far = token Jaccard with the reference < 0.3 and no substring relation either way.
    """
    ref = row.answers[0][0]
    cands = sorted(
        {
            other.answers[0][0]
            for other in pool
            if other.article == row.article and other.qid != row.qid
        }
    )
    cands = [
        c for c in cands if token_jaccard(c, ref) < JACCARD_MAX and not contains_either(c, ref)
    ]
    return cands[int(rng.integers(len(cands)))] if cands else None


SET_OF = {"answer_correctness": "correctness", "perturbation_consistency": "consistency"}


def _item(
    metric: str,
    row: QuadRow,
    *,
    candidate: str,
    label: int,
    construction: str,
    hard_type: str | None = None,
    trivial: bool = False,
) -> CalibrationItem:
    inputs = {"frage": row.question, "referenz": row.answers[0][0], "antwort": candidate}
    cluster = "germanquad:" + row.article
    return CalibrationItem(
        item_id=make_item_id(SET_OF[metric], cluster, construction, inputs),
        metric=metric,
        cluster_id=cluster,
        inputs=inputs,
        label=label,
        source="germanquad",
        construction=construction,
        trivial=trivial,
        hard_negative=hard_type is not None,
        hard_type=hard_type,
    )


def _valid_edit(ref: str, cand: str, label: int, kind: str, texts: Sequence[str]) -> bool:
    """Validity filters of a correctness hard negative (review of #107, D863)."""
    if norm(cand) == norm(ref):
        return False
    if label == 0 and any(contains_either(cand, t) for t in texts):
        return False
    if kind == "negation_flip" and not negation_ok(ref, cand):
        return False
    if kind == "partial_answer":
        return has_answer_content(cand) and all(norm(cand) != norm(t) for t in texts)
    return True


def correctness_hard(row: QuadRow, rng: np.random.Generator) -> list[CalibrationItem]:
    """The four constructed hard negatives of one question (each only when it exists)."""
    ref = row.answers[0][0]
    texts = [t for t, _ in row.answers]
    edits: list[tuple[str | None, int, str]] = [
        (same_paragraph_span(row.context, row.answers, ref, rng), 0, "same_paragraph_span"),
        (swap_first_number(ref), 0, "number_date_swap"),
        (negate(ref), 0, "negation_flip"),
        (partial(ref), 1, "partial_answer"),
    ]
    out: list[CalibrationItem] = []
    for cand, label, kind in edits:
        if cand is None or not _valid_edit(ref, cand, label, kind, texts):
            continue
        out.append(
            _item(
                "answer_correctness",
                row,
                candidate=cand,
                label=label,
                construction=kind,
                hard_type=kind,
            )
        )
    return out


def annotators_agree(first: str, second: str) -> bool:
    """True iff two annotator answers share a token or one contains the other (D863).

    Disjoint answers (e.g. "1907" vs. "Zusammenschluss des City and Guilds College ...") read the
    question differently; such a pair is not a reliable positive and is skipped.
    """
    return token_jaccard(first, second) > 0 or contains_either(first, second)


def _nontrivial_agreeing(first: str, second: str) -> bool:
    return norm(first) != norm(second) and annotators_agree(first, second)


def build_correctness(
    rows: Sequence[QuadRow], pool: Sequence[QuadRow], seed: int
) -> list[CalibrationItem]:
    """Build the ``correctness`` set (50 / 50 after seeded down-sampling).

    Args:
        rows: The sampled questions (:func:`sample_questions`).
        pool: All test questions (source of other-question negatives).
        seed: Seed of every random choice.

    Returns:
        Positives (annotator answer 2, when the annotators agree) followed by the balanced
        negatives.
    """
    rng = np.random.default_rng(seed)
    pos: list[CalibrationItem] = []
    hard: list[CalibrationItem] = []
    other: list[CalibrationItem] = []
    for row in rows:
        ref, cand = row.answers[0][0], row.answers[1][0]
        if annotators_agree(ref, cand):
            pos.append(
                _item(
                    "answer_correctness",
                    row,
                    candidate=cand,
                    label=2,
                    construction="annotator_answer_2",
                    trivial=norm(cand) == norm(ref),
                )
            )
        hard.extend(correctness_hard(row, rng))
        off = other_answer(row, pool, rng)
        if off is not None:
            other.append(
                _item(
                    "answer_correctness", row, candidate=off, label=0, construction="other_question"
                )
            )
    return balance(pos, hard, other, rng)


def build_consistency(
    rows: Sequence[QuadRow], pool: Sequence[QuadRow], seed: int
) -> list[CalibrationItem]:
    """Build the ``consistency`` set (``referenz`` = answer 1, ``antwort`` = the variant).

    Consistent (1): annotator answer 2 when not trivial, and a fixed frame around answer 1.
    Inconsistent (0): another question's answer (Jaccard rule) and ``swap_first_number``.
    """
    rng = np.random.default_rng(seed + 1)
    out: list[CalibrationItem] = []
    for i, row in enumerate(rows):
        ref, second = row.answers[0][0], row.answers[1][0]
        cands: list[tuple[str | None, int, str]] = [
            (second if _nontrivial_agreeing(ref, second) else None, 1, "annotator_answer_2"),
            (frame(ref, seed=seed + i), 1, "frame"),
            (other_answer(row, pool, rng), 0, "other_question"),
            (swap_first_number(ref), 0, "number_date_swap"),
        ]
        for cand, label, kind in cands:
            if cand is None:
                continue
            hard = "number_date_swap" if kind == "number_date_swap" else None
            out.append(
                _item(
                    "perturbation_consistency",
                    row,
                    candidate=cand,
                    label=label,
                    construction=kind,
                    hard_type=hard,
                )
            )
    return out
