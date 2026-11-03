"""Near-duplicate filter ``dedupe`` (T4.3): fixed numeric vectors, no model."""

from collections.abc import Sequence

import numpy as np
import pytest
from numpy.typing import NDArray

from pruefstand.core.errors import DatasetError
from pruefstand.core.ids import ChunkId
from pruefstand.core.models.dataset import QACandidate
from pruefstand.dataset.filters import dedupe, dedupe_report
from pruefstand.dataset.to_case import case_id_of

QUESTIONS = ["q1", "q2", "q3"]
VECTORS = {"q1": [1.0, 0.0, 0.0], "q2": [0.95, 0.31225, 0.0], "q3": [0.5, 0.0, 0.866]}


def embed(texts: Sequence[str]) -> NDArray[np.float32]:
    return np.array([VECTORS[t] for t in texts], dtype=np.float32)


def _cand(question: str) -> QACandidate:
    return QACandidate(
        question=question,
        answer="a",
        citation=None,
        chunk_id=ChunkId("gii-bgb-622#1"),
        prompt_version="qa_factual_de_v1",
    )


def test_dedupe_drops_the_second_of_two_near_identical_questions() -> None:
    cands = [_cand(q) for q in QUESTIONS]
    kept = dedupe(cands, embed, 0.9)
    assert {c.question for c in kept} == {"q1", "q3"} or {c.question for c in kept} == {"q2", "q3"}
    assert len(kept) == 2


def test_dedupe_keeps_the_same_candidates_for_any_input_order() -> None:
    cands = [_cand(q) for q in QUESTIONS]
    expected = [c.question for c in dedupe(cands, embed, 0.9)]
    for seed in range(6):
        shuffled = cands[:]
        order = np.random.default_rng(seed).permutation(len(shuffled))
        shuffled = [cands[i] for i in order]
        assert [c.question for c in dedupe(shuffled, embed, 0.9)] == expected


def test_dedupe_keeps_the_lower_id_of_a_duplicate_pair() -> None:
    c1, c2 = _cand("q1"), _cand("q2")
    keep = min([c1, c2], key=case_id_of)
    assert dedupe([c1, c2], embed, 0.9) == [keep]


def test_the_boundary_cosine_counts_as_a_duplicate() -> None:
    c1, c2 = _cand("q1"), _cand("q2")
    vectors = {"q1": [1.0, 0.0], "q2": [0.9, float(np.sqrt(1 - 0.81))]}
    fn = lambda texts: np.array([vectors[t] for t in texts], dtype=np.float32)  # noqa: E731
    assert len(dedupe([c1, c2], fn, 0.9 - 1e-6)) == 1
    assert len(dedupe([c1, c2], fn, 0.95)) == 2


def test_dedupe_report_names_the_dropped_and_rejects_bad_embeddings() -> None:
    kept, dropped = dedupe_report([_cand(q) for q in QUESTIONS], embed, 0.9)
    assert len(kept) == 2
    assert len(dropped) == 1
    assert dedupe([], embed) == []
    with pytest.raises(DatasetError):
        dedupe([_cand("q1")], lambda t: np.zeros((len(t), 3), dtype=np.float32))
    with pytest.raises(DatasetError):
        dedupe([_cand("q1"), _cand("q2")], lambda t: np.ones((1, 3), dtype=np.float32))
