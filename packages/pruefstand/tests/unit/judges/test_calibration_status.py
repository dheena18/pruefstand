"""T5.4 S11: per-judge drift threshold and self-agreement in ``calibration_status.yaml``."""

from pathlib import Path

import pytest

from pruefstand.core.errors import ConfigError
from pruefstand.judges.calibration import read_status as reexported
from pruefstand.judges.status import drift_threshold_of, read_status

TEXT = """epoch: 1
passed: false
judges:
  ollama/gemma3:12b: {drift_threshold: 6, a0: 0.98, metrics: {}}
  github/x: {drift_threshold: true, a0: "n/a"}
"""


def test_per_judge_threshold_and_a0_are_read(tmp_path: Path) -> None:
    path = tmp_path / "s.yaml"
    path.write_text(TEXT, encoding="utf-8")
    status = read_status(path)
    assert status is not None
    assert status.drift_thresholds == {"ollama/gemma3:12b": 6}  # a bool is not a threshold
    assert status.self_agreement == {"ollama/gemma3:12b": 0.98}
    assert drift_threshold_of("ollama/gemma3:12b", path) == 6
    assert drift_threshold_of("github/x", path) is None


def test_a_file_without_judges_still_reads_and_the_old_path_works(tmp_path: Path) -> None:
    path = tmp_path / "s.yaml"
    path.write_text("epoch: 2\npassed: true\n", encoding="utf-8")
    status = reexported(path)
    assert status is not None
    assert status.passed is True
    assert status.drift_thresholds == {}


def test_a_threshold_above_the_cap_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "s.yaml"
    path.write_text("epoch: 1\njudges:\n  ollama/x: {drift_threshold: 11}\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="above"):
        read_status(path)
