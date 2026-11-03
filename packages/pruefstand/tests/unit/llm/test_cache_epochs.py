"""Cache epochs (S13): a cache-key suffix only, never part of eval_fingerprint (X3.3)."""

import json
from pathlib import Path

import pytest

from pruefstand.core.errors import ConfigError
from pruefstand.llm.cache_epochs import (
    clear_drift,
    current_epoch,
    drift_file,
    invalidate_judge,
    read_drift,
)

JUDGE = "ollama/gemma3:12b"


def test_a_missing_file_means_epoch_zero(tmp_path: Path) -> None:
    assert current_epoch(tmp_path, JUDGE) == 0


def test_invalidate_bumps_only_that_model(tmp_path: Path) -> None:
    assert invalidate_judge(tmp_path, JUDGE) == 1
    assert invalidate_judge(tmp_path, JUDGE) == 2
    assert current_epoch(tmp_path, JUDGE) == 2
    assert current_epoch(tmp_path, "github/x") == 0
    assert json.loads((tmp_path / "cache_epochs.json").read_text(encoding="utf-8")) == {JUDGE: 2}


def test_clear_drift_removes_the_flag_and_keeps_the_epoch(tmp_path: Path) -> None:
    invalidate_judge(tmp_path, JUDGE)
    drift_file(tmp_path).write_text(
        json.dumps({"model": JUDGE, "agreement": 0.7, "epoch": 1, "ts": "2026-11-03T02:00:00Z"}),
        encoding="utf-8",
    )
    flag = read_drift(tmp_path)
    assert flag is not None
    assert flag.model == JUDGE
    assert flag.epoch == 1
    clear_drift(tmp_path, JUDGE)
    assert read_drift(tmp_path) is None
    assert current_epoch(tmp_path, JUDGE) == 1


def test_clear_drift_leaves_another_judges_flag(tmp_path: Path) -> None:
    drift_file(tmp_path).write_text(
        json.dumps({"model": "github/x", "agreement": 0.7, "epoch": 1, "ts": "t"}), encoding="utf-8"
    )
    clear_drift(tmp_path, JUDGE)
    assert read_drift(tmp_path) is not None


def test_a_corrupt_epoch_file_is_a_config_error(tmp_path: Path) -> None:
    (tmp_path / "cache_epochs.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ConfigError):
        current_epoch(tmp_path, JUDGE)
