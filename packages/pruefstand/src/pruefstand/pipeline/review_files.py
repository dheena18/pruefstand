"""Paths and readers shared by the review steps (T4.7a)."""

from pathlib import Path

from pydantic import BaseModel, ValidationError

from pruefstand.core.config import DatasetBuildConfig, ReviewConfig
from pruefstand.core.errors import ConfigError, DatasetError
from pruefstand.core.models.dataset import DatasetManifest, ReviewItem, SpotDecision
from pruefstand.core.models.testcase import TestCase
from pruefstand.dataset.io import read_dataset

SAMPLE = "sample.jsonl"
ITEMS = "items.jsonl"
SPOT_SAMPLE = "spotcheck_sample.jsonl"
SPOT_DECISIONS = "spotcheck_decisions.jsonl"
SPOTCHECK_VERSION = "spotcheck"
APPLIED = "applied.txt"


def review_dir(cfg: DatasetBuildConfig) -> Path:
    """The review artefact directory of the build described by ``cfg``."""
    return cfg.work_dir / f"{cfg.name}-{cfg.dataset_version}" / "review"


def dataset_dir(cfg: DatasetBuildConfig) -> Path:
    """The dataset directory the build wrote."""
    return cfg.out_dir / cfg.name / cfg.dataset_version


def require_review(cfg: DatasetBuildConfig) -> ReviewConfig:
    """Return ``cfg.review``.

    Raises:
        ConfigError: The config has no ``review`` or ``models`` block.
    """
    if cfg.review is None or cfg.models is None:
        msg = "dataset.yaml has no review: block (reviewers) or no models: block"
        raise ConfigError(msg)
    return cfg.review


def _read_lines[M: BaseModel](path: Path, model: type[M]) -> list[M]:
    if not path.is_file():
        return []
    rows: list[M] = []
    for line in path.read_text("utf-8").splitlines():
        try:
            rows.append(model.model_validate_json(line))
        except ValidationError:
            continue  # a truncated last line of an interrupted run
    return rows


def read_items(cfg: DatasetBuildConfig) -> list[ReviewItem]:
    """The review items written so far (last item per case wins)."""
    items = _read_lines(review_dir(cfg) / ITEMS, ReviewItem)
    return list({i.case_id: i for i in items}.values())


def read_decisions(cfg: DatasetBuildConfig) -> list[SpotDecision]:
    """The owner's spot-check decisions (last decision per case wins)."""
    rows = _read_lines(review_dir(cfg) / SPOT_DECISIONS, SpotDecision)
    return list({d.case_id: d for d in rows}.values())


def read_cases(cfg: DatasetBuildConfig) -> tuple[list[TestCase], DatasetManifest]:
    """Read every case and the manifest of the built dataset.

    Raises:
        DatasetError: The dataset cannot be read.
    """
    loaded = read_dataset(dataset_dir(cfg))
    if loaded.manifest is None or loaded.problems:
        msg = f"{dataset_dir(cfg)}: cannot read the dataset ({'; '.join(loaded.problems[:2])})"
        raise DatasetError(msg)
    return [c for cases in loaded.cases.values() for c in cases], loaded.manifest
