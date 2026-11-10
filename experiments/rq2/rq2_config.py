"""The RQ2 run configuration (``configs/rq2_judges.yaml``) and the label-set loader."""

import json
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict
from rq2.calib_schema import CalibrationItem

from pruefstand.core.errors import ConfigError

REPO = Path(__file__).resolve().parents[2]
Split = Literal["dev", "test"]


class JudgeEntry(BaseModel):
    """One candidate judge (arm ``a``, ``a2`` swap, ``b1`` large, ``b2`` size, ``c`` tier 1)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    family: str
    arm: Literal["a", "a2", "b1", "b2", "c"]
    enabled: bool = True
    subsample: int | None = None


class SetEntry(BaseModel):
    """One label set of T5.3."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    path: str
    origin: Literal["human", "construction"]
    local_only: bool = False
    pending: bool = False


class RQ2Config(BaseModel):
    """The whole RQ2 configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    seed: int
    generator: str
    concurrency: int = 4
    cache_dir: str
    out_dir: str
    judges: tuple[JudgeEntry, ...]
    datagen_family: str
    sets: tuple[SetEntry, ...]
    gating: dict[str, tuple[str, ...]]

    def set_named(self, name: str) -> SetEntry:
        """Return the set called ``name``.

        Raises:
            ConfigError: No such set.
        """
        for entry in self.sets:
            if entry.name == name:
                return entry
        msg = f"unknown label set {name!r}"
        raise ConfigError(msg)


def load_config(path: Path) -> RQ2Config:
    """Read and validate the RQ2 config."""
    return RQ2Config.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def set_available(entry: SetEntry, root: Path = REPO) -> bool:
    """Whether the set file exists and the set is not marked pending."""
    return not entry.pending and (root / entry.path).is_file()


def load_items(entry: SetEntry, split: Split | None, root: Path = REPO) -> list[CalibrationItem]:
    """Load the items of one set, optionally only one ``calib_split``.

    Raises:
        ConfigError: The set is pending or its file is missing.
    """
    if not set_available(entry, root):
        msg = f"label set {entry.name!r} is not available ({entry.path})"
        raise ConfigError(msg)
    lines = (root / entry.path).read_text(encoding="utf-8").splitlines()
    items = [CalibrationItem.model_validate(json.loads(line)) for line in lines if line.strip()]
    return [i for i in items if split is None or i.calib_split == split]


def slug(model_id: str) -> str:
    """File-name slug of a model id (``ollama/gemma3:12b`` -> ``ollama_gemma3-12b``).

    >>> slug("ollama/gemma3:12b")
    'ollama_gemma3-12b'
    """
    return model_id.replace("/", "_").replace(":", "-")
