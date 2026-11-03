"""Dataset models (interfaces §14): the manifest of a dataset version and its review rounds."""

import datetime as dt
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pruefstand.core.enums import Lang, Split
from pruefstand.core.ids import ChunkId


class ReviewRound(BaseModel):
    """One human review round over a sample of generated cases."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    round: int
    prompt_version: str
    sampled: int
    bad: int
    error_rate: float
    reviewer: str
    date: dt.date


class DatasetManifest(BaseModel):
    """``dataset_manifest.json`` of ``datasets/<name>/<version>/`` (interfaces §1.3, §14).

    ``blocks`` holds the case counts per nightly block of ``full`` (keys ``"refusal"``, ``"0"``,
    ``"1"``, ``"2"``, R12 N1.1); ``judged_subset`` is the number of ``core`` cases flagged for the
    judged subset (150); ``assignment_seed`` is the seed ``assign_splits`` used for both.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    version: str
    created_at: dt.datetime
    corpus_version: str
    splits: dict[Split, int]
    license_configs: dict[str, str]
    prompt_versions: dict[str, str]
    review: tuple[ReviewRound, ...]
    blocks: dict[str, int] = {}
    judged_subset: int = 0
    assignment_seed: int = 0


class QACandidate(BaseModel):
    """One generated question with its reference answer, before filtering (T4.2, interfaces §14).

    ``chunk_id`` is the chunk that carries the gold answer; ``extra_chunk_ids`` holds the second
    chunk of a multi-hop or cross-lingual pair (empty for single-chunk categories).
    ``evidence_span`` is the model's ``evidence`` when it is a verbatim span of the cited Absatz of
    the source chunk (<= 60 tokens), else None. ``lang`` is the language of the question.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    question: str
    answer: str
    citation: str | None
    chunk_id: ChunkId
    prompt_version: str
    evidence_span: str | None = None
    extra_chunk_ids: tuple[ChunkId, ...] = ()
    lang: Lang = Lang.DE
    style: Literal["laie", "fachlich"] | None = None


FILTER_REASONS = frozenset(
    {
        "unsupported",
        "ngram_overlap",
        "long_copy",
        "meta_reference",
        "near_duplicate",
        "judge_error",
        "chunk_missing",
        "citation_mismatch",
        "evidence_off_paragraph",
        "evidence_not_in_cited_absatz",
        "evidence_too_short",
        "evidence_missing",
        "citation_missing",
        "citation_unparsed",
        "cluster_overlap",
    }
)


class FilterResult(BaseModel):
    """Verdict of one QA filter (T4.3, interfaces §14).

    reasons come from the fixed vocabulary FILTER_REASONS and kept is true exactly
    when there is none.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kept: bool
    reasons: tuple[str, ...]

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        unknown = set(self.reasons) - FILTER_REASONS
        if unknown:
            msg = f"unknown filter reasons {sorted(unknown)}"
            raise ValueError(msg)
        if self.kept == bool(self.reasons):
            msg = "kept must be true exactly when there are no reasons"
            raise ValueError(msg)
        return self


class FilterConfig(BaseModel):
    """Thresholds of the QA filters (T4.3); the defaults are the values of SPEC 3.5 step 3.

    max_ngram_overlap: share of the question 6-grams that may occur in a source chunk (0.0 =
    none); long_copy_words: a shared run of this many words is a copy; max_sim: cosine
    from which a question is a near-duplicate; min_laie_share / style_min_n: report-level
    check of the layperson share (evaluated from style_min_n candidates on).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_ngram_overlap: float = Field(default=0.0, ge=0.0, le=1.0)
    long_copy_words: int = Field(default=8, ge=2)
    max_sim: float = Field(default=0.9, gt=0.0, le=1.0)
    min_laie_share: float = Field(default=0.6, ge=0.0, le=1.0)
    style_min_n: int = Field(default=20, ge=1)
    concurrency: int = Field(default=4, ge=1)
