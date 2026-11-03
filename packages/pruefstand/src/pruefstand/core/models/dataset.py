"""Dataset models (interfaces §14): the manifest of a dataset version and its review rounds."""

import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict

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
