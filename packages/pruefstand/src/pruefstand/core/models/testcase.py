"""The test case model (interfaces §2, SPEC §3.3)."""

from typing import Any, Self

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from pruefstand.core.enums import Category, Difficulty, Lang, Split
from pruefstand.core.ids import CaseId, DocId, TenantId

_PROBE_CATEGORIES = frozenset(
    {Category.LEAK_PROBE, Category.FILTER_BYPASS, Category.SYSTEM_PROMPT_EXTRACTION}
)
_BLOCKS = frozenset({0, 1, 2})


class TestCase(BaseModel):
    """One evaluation case (one line of ``datasets/<name>/<version>/<split>.jsonl``).

    ``cluster_id`` is the bootstrap cluster (source document of the base question). When the
    input has no ``cluster_id`` it defaults to the first ``gold_doc_ids`` entry, else ``base_id``.

    Raises:
        ValidationError: ``perturbation is None`` but ``base_id != id``; ``unanswerable`` without
            ``expect_refusal``; ``injection`` without ``injection_marker``; a leak, filter-bypass or
            system-prompt probe without ``forbidden_strings``; a blank question; ``block`` set
            outside ``split == full`` or not in {0, 1, 2}; ``judged_subset`` outside ``core``.
    """

    __test__ = False  # D9-35: a dunder is ignored by pydantic; stops PytestCollectionWarning
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: CaseId
    base_id: CaseId
    cluster_id: str
    tenant: TenantId
    lang: Lang
    question: str
    reference_answer: str | None
    gold_doc_ids: tuple[DocId, ...] = ()
    gold_citations: tuple[str, ...] = ()
    evidence_span: str | None = None
    category: Category
    difficulty: Difficulty
    split: Split
    expect_refusal: bool = False
    injection_marker: str | None = None
    forbidden_strings: tuple[str, ...] = ()
    perturbation: str | None = None
    source: str
    license_config: str
    generation_prompt_version: str | None = None
    corpus_version: str
    tags: tuple[str, ...] = ()
    block: int | None = None
    judged_subset: bool = False

    @model_validator(mode="before")
    @classmethod
    def _default_cluster_id(cls, data: Any) -> Any:  # noqa: ANN401  (pydantic hook: any input shape)
        if not isinstance(data, dict) or data.get("cluster_id") is not None:
            return data
        gold = data.get("gold_doc_ids") or ()
        fallback = gold[0] if gold else data.get("base_id")
        return data if fallback is None else {**data, "cluster_id": fallback}

    @field_validator("question")
    @classmethod
    def _question_not_blank(cls, value: str) -> str:
        if not value.strip():
            msg = "question must not be blank"
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def _check_consistency(self) -> Self:
        if self.perturbation is None and self.base_id != self.id:
            msg = f"base_id {self.base_id!r} must equal id {self.id!r} when perturbation is None"
            raise ValueError(msg)
        if self.category is Category.UNANSWERABLE and not self.expect_refusal:
            msg = "category unanswerable requires expect_refusal"
            raise ValueError(msg)
        if self.category is Category.INJECTION and self.injection_marker is None:
            msg = "category injection requires injection_marker"
            raise ValueError(msg)
        if self.category in _PROBE_CATEGORIES and not self.forbidden_strings:
            msg = f"category {self.category.value} requires non-empty forbidden_strings"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _check_block_and_subset(self) -> Self:
        if self.block is not None and (self.split is not Split.FULL or self.block not in _BLOCKS):
            msg = f"block {self.block} requires split full and a value in {{0, 1, 2}}"
            raise ValueError(msg)
        if self.judged_subset and self.split is not Split.CORE:
            msg = "judged_subset requires split core"
            raise ValueError(msg)
        return self
