"""The ``answer_fact_not_in_source`` rule must not reject correct reference answers (T4.7a).

Regression for the hand-checked answers of the slice fixtures (``slice-015`` among them) and the
twelve answers of the build tests; the wrong answer of the recorded review stays caught.
"""

from collections import defaultdict
from collections.abc import Iterator

import pytest
from testsupport.build_support import QA
from testsupport.qa_support import REPO, slice_chunks

from pruefstand.core.models.corpus import Chunk
from pruefstand.core.models.testcase import TestCase
from pruefstand.dataset.io import read_split
from pruefstand.dataset.review_checks import (
    ANSWERABLE,
    deterministic_problems,
    source_chunks_of,
    unsupported_facts,
)

FIXTURES = REPO / "datasets" / "fixtures" / "slice_v1"
FILES = ("smoke.jsonl", "smoke_live.jsonl")


def _by_doc() -> dict[str, list[Chunk]]:
    docs: dict[str, list[Chunk]] = defaultdict(list)
    for chunk in slice_chunks().values():
        docs[chunk.doc_id].append(chunk)
    return docs


def _answerable() -> Iterator[tuple[str, TestCase]]:
    for name in FILES:
        cases, problems = read_split(FIXTURES / name)
        assert problems == []
        for case in cases:
            if case.category in ANSWERABLE and case.reference_answer:
                yield f"{name}:{case.id}", case


def _rejected(case: TestCase, by_doc: dict[str, list[Chunk]]) -> bool:
    pool = [c for d in case.gold_doc_ids for c in by_doc.get(d, ())]
    found = deterministic_problems(case, source_chunks_of(case, by_doc), pool)
    return "answer_fact_not_in_source" in found


def test_no_correct_fixture_answer_is_rejected() -> None:
    by_doc = _by_doc()
    cases = list(_answerable())
    assert len(cases) >= 10
    rejected = [name for name, case in cases if _rejected(case, by_doc)]
    assert rejected == []


def test_slice_015_is_not_rejected() -> None:
    by_doc = _by_doc()
    found = [case for name, case in _answerable() if name.endswith(":slice-015")]
    assert found
    assert not _rejected(found[0], by_doc)


@pytest.mark.parametrize(("chunk_id", "question", "answer"), QA, ids=lambda v: str(v)[:24])
def test_the_hand_written_build_answers_are_supported(
    chunk_id: str, question: str, answer: str
) -> None:
    chunk = slice_chunks()[chunk_id]
    assert unsupported_facts(answer, f"{question} {chunk.text} {chunk.citation_key}") == []
