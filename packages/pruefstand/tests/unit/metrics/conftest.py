"""Builders for the metric tests: real ``TestCase`` / ``TargetResponse`` objects, no fakes."""

from collections.abc import Sequence
from typing import Any

import pytest

from pruefstand.core.models.target import RetrievedChunk, TargetResponse
from pruefstand.core.models.testcase import TestCase
from testsupport.metric_types import CaseFactory, ChunkFactory, RespFactory

_BASE: dict[str, Any] = {
    "id": "law-0042",
    "base_id": "law-0042",
    "tenant": "kanzlei_mueller",
    "lang": "de",
    "question": "Welche Kündigungsfrist gilt für den Arbeitgeber nach zwei Jahren?",
    "reference_answer": "Einen Monat zum Ende eines Kalendermonats (§ 622 Abs. 2 Nr. 1 BGB).",
    "gold_doc_ids": ["bgb-622"],
    "gold_citations": ["§ 622 Abs. 2 BGB"],
    "category": "factual",
    "difficulty": "easy",
    "split": "core",
    "source": "generated+reviewed",
    "license_config": "laws_eurlex",
    "corpus_version": "2026-11-02.ab12cd34",
}


@pytest.fixture
def make_case() -> CaseFactory:
    """Build a valid ``TestCase``; keyword arguments override the factual default."""

    def build(**changes: Any) -> TestCase:  # noqa: ANN401  (test builder: any field value)
        return TestCase.model_validate({**_BASE, **changes})

    return build


@pytest.fixture
def make_chunk() -> ChunkFactory:
    """Build a ``RetrievedChunk``."""

    def build(
        doc_id: str = "bgb-622",
        *,
        tenant: str | None = "shared_public",
        text: str = "Text.",
        rank: int = 1,
    ) -> RetrievedChunk:
        return RetrievedChunk(
            chunk_id=f"{doc_id}#{rank}",
            doc_id=doc_id,
            tenant_id=tenant,
            text=text,
            score=1.0 / rank,
            rank=rank,
        )

    return build


@pytest.fixture
def make_resp() -> RespFactory:
    """Build a ``TargetResponse``; ``chunks=None`` means the target returned none."""

    def build(
        answer: str = "",
        *,
        citations: Sequence[str] = (),
        chunks: Sequence[RetrievedChunk] | None = None,
        refused: bool | None = None,
    ) -> TargetResponse:
        return TargetResponse(
            answer=answer,
            citations=tuple(citations),
            chunks=None if chunks is None else tuple(chunks),
            refused=refused,
        )

    return build
