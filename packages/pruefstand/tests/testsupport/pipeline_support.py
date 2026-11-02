"""Helpers of the pipeline and CLI tests (T1.10): tmp datasets, configs, cassette-backed targets."""

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml
from testsupport.run_builders import make_case

from pruefstand.core.config import PruefstandConfig, RunnerConfig, TargetConfig
from pruefstand.core.config_loader import load_config
from pruefstand.core.enums import Split
from pruefstand.core.models.testcase import TestCase

ROOT = Path(__file__).resolve().parents[4]
MINI_CONFIG = ROOT / "examples" / "live" / "mini.yaml"
MINI_DATASET = ROOT / "datasets" / "fixtures" / "mini_v0"
CORPUS_VERSION = "2026-11-02.ab12cd34"  # the default of run_builders.make_case
BASE = "http://target.test"
GOOD_URL = "http://localhost:8000"
BUG_URL = "http://localhost:8001"
QUERY_OK = (
    "Die Kündigungsfrist beträgt einen Monat zum Ende eines Kalendermonats (§ 622 Abs. 2 BGB)."
)


def case_rows(cases: Sequence[TestCase]) -> list[dict[str, Any]]:
    """JSON-ready rows of ``cases``."""
    return [json.loads(c.model_dump_json()) for c in cases]


def write_dataset(
    root: Path,
    rows: Mapping[str, Sequence[Mapping[str, Any] | TestCase | str]],
    *,
    name: str = "tmpset",
    version: str = "v1",
    corpus_version: str = CORPUS_VERSION,
) -> Path:
    """Write ``<root>/<name>/<version>/<split>.jsonl`` and ``dataset_manifest.json``.

    A ``str`` row is written verbatim (to plant a broken line); a ``TestCase`` is serialised.
    """
    directory = root / name / version
    directory.mkdir(parents=True)
    for split, items in rows.items():
        lines = []
        for item in items:
            if isinstance(item, str):
                lines.append(item)
            elif isinstance(item, TestCase):
                lines.append(item.model_dump_json())
            else:
                lines.append(json.dumps(item, ensure_ascii=False))
        (directory / f"{split}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    manifest = {
        "name": name,
        "version": version,
        "created_at": "2026-11-02T00:00:00Z",
        "corpus_version": corpus_version,
        "splits": {split: len(items) for split, items in rows.items()},
        "license_configs": {"laws_eurlex": "CC BY 4.0"},
        "prompt_versions": {},
        "review": [],
    }
    (directory / "dataset_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    return directory


def mini_config(**changes: Any) -> PruefstandConfig:
    """The committed mini config with fast runner settings; keyword arguments replace fields."""
    cfg = load_config(MINI_CONFIG)
    update: dict[str, Any] = {
        "dataset": str(MINI_DATASET),
        "runner": RunnerConfig(concurrency=4, timeout_s=5, max_retries=0, backoff_s=0.001),
    }
    update.update(changes)
    return cfg.model_copy(update=update)


def synthetic_config(
    dataset: Path, splits: Sequence[Split] = (Split.CORE,), **changes: Any
) -> PruefstandConfig:
    """A config for ``BASE`` and a tmp dataset directory."""
    target = TargetConfig(type="http", url=BASE, timeout_s=5)
    return mini_config(target=target, dataset=str(dataset), splits=tuple(splits), **changes)


def config_file(path: Path, cfg: PruefstandConfig) -> Path:
    """Write ``cfg`` as YAML so the CLI can load it."""
    path.write_text(
        yaml.safe_dump(json.loads(cfg.model_dump_json()), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return path


def first_line(text: str) -> str:
    """The first line of ``text``."""
    return text.splitlines()[0]
