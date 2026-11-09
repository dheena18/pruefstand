"""Paths and readers shared by the review steps (T4.7a)."""

import shutil
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel, ValidationError

from pruefstand.core.config import DatasetBuildConfig, ReviewConfig
from pruefstand.core.errors import ConfigError, DatasetError
from pruefstand.core.models.dataset import DatasetManifest, ReviewItem, SpotDecision
from pruefstand.core.models.testcase import TestCase
from pruefstand.dataset.io import read_dataset, write_dataset
from pruefstand.dataset.validate import validate_dataset

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
    """Read a JSON-lines file; only a truncated last line (an interrupted write) is skipped."""
    if not path.is_file():
        return []
    lines = path.read_text("utf-8").splitlines()
    rows: list[M] = []
    for number, line in enumerate(lines, start=1):
        try:
            rows.append(model.model_validate_json(line))
        except ValidationError as exc:
            if number == len(lines):
                continue
            msg = f"{path.name}:{number}: not a valid {model.__name__}"
            raise DatasetError(msg) from exc
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


def replace_dataset(directory: Path, cases: Sequence[TestCase], manifest: DatasetManifest) -> None:
    """Write the dataset beside ``directory``, validate it, then swap (a failure keeps the old).

    Raises:
        DatasetError: The new dataset does not validate (the old one stays).
    """
    staging = directory.with_name(directory.name + ".new")
    shutil.rmtree(staging, ignore_errors=True)
    write_dataset(staging, cases, manifest)
    problems = validate_dataset(staging)
    if problems:
        shutil.rmtree(staging, ignore_errors=True)
        msg = (
            f"{directory}: {len(problems)} problems, first: {problems[0]}; the old dataset is kept"
        )
        raise DatasetError(msg)
    shutil.rmtree(directory, ignore_errors=True)
    staging.rename(directory)
