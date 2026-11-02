"""Dataset models (interfaces §14): the manifest of a dataset version and its review rounds."""

import datetime as dt

from pydantic import BaseModel, ConfigDict

from pruefstand.core.enums import Split


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
