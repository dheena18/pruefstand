"""``pruefstand build-dataset`` (T4.7a): usage errors, the printed counts and the stage option."""

import re
from pathlib import Path

import pytest
import yaml
from testsupport.build_support import SLICE_DIR, offline_clients, small_plan, write_candidates
from typer.testing import CliRunner

from pruefstand.cli import app
from pruefstand.core.config import DatasetBuildConfig, EmbedConfig, GenerationConfig


def _config_file(tmp_path: Path) -> Path:
    cfg = DatasetBuildConfig(
        name="pruefstand-de-small",
        dataset_version="v1",
        corpus_dir=SLICE_DIR,
        out_dir=tmp_path / "datasets" / "fixtures",
        work_dir=tmp_path / "work",
        split_plan=small_plan(),
        seed=5,
        generation=GenerationConfig(candidates_from=write_candidates(tmp_path / "c.jsonl")),
        embed=EmbedConfig(url="http://embed.invalid"),
        check_refusal_laws=False,
    )
    path = tmp_path / "dataset.yaml"
    path.write_text(yaml.safe_dump(cfg.model_dump(mode="json")), encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "pruefstand.pipeline.build_dataset.default_clients", lambda _root: offline_clients()
    )


def test_the_command_is_registered_and_not_a_stub() -> None:
    env = {"NO_COLOR": "1", "COLUMNS": "200", "TERM": "dumb", "FORCE_COLOR": None}
    result = CliRunner().invoke(app, ["build-dataset", "--help"], env=env)
    assert result.exit_code == 0
    text = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
    for option in ("--stage", "--resume", "--only", "--config"):
        assert option in text


def test_a_missing_config_is_a_usage_error(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["build-dataset", "--config", str(tmp_path / "no.yaml")])
    assert result.exit_code == 2


def test_an_unknown_stage_is_a_usage_error(tmp_path: Path) -> None:
    args = ["build-dataset", "--config", str(_config_file(tmp_path)), "--stage", "nope"]
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 2
    assert "unknown stage" in result.output


def test_a_build_prints_the_split_counts_and_the_dropped_licences(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["build-dataset", "--config", str(_config_file(tmp_path))])
    assert result.exit_code == 0, result.output
    assert "splits:" in result.output
    assert "smoke=" in result.output
    assert "dropped_mixed_license=0" in result.output


def test_one_stage_prints_its_counters(tmp_path: Path) -> None:
    args = ["build-dataset", "--config", str(_config_file(tmp_path)), "--stage", "generate"]
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output
    assert "generate:" in result.output
    assert "dropped_mixed_license=0" in result.output
