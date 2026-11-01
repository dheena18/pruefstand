"""Only ConfigError escapes load_config (second review of PR #7)."""

import contextlib
from pathlib import Path

import pytest
from pydantic import ValidationError

from pruefstand.core.config import GatePolicy
from pruefstand.core.config_loader import load_config
from pruefstand.core.errors import ConfigError

# --- only ConfigError escapes load_config (second review of PR #7) ---

GATE_FIELDS = (
    "hard_fail",
    "metrics",
    "slices",
    "gated_slices",
    "min_clusters",
    "n_resamples",
    "correction",
    "alpha",
    "warn_p",
    "max_error_rate",
)
HOSTILE = ("", "null", "5", "1.5", "true", "abc", "[]", "[1]", "[[1]]", "{}", "{a: 1}", "{a: [1]}")

MINIMAL = """\
version: 1
target: {type: http, url: "http://localhost:8000"}
dataset: d
splits: [smoke]
generator_family: qwen
judge:
  pr: {id: "ollama/gemma3:12b", family: gemma}
  nightly: {id: "ollama/gemma3:12b", family: gemma}
gate:
  metrics:
    context_recall: {max_drop: 0.05}
budget: {}
runner: {}
baseline_store: {type: local_dir, path: baselines}
"""


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "pruefstand.yaml"
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.parametrize("value", ["5", "null", "abc", "{a: 1}", "[[1]]", "1.5", "true"])
def test_non_sequence_slices_give_config_error(value: str, tmp_path: Path) -> None:
    text = MINIMAL.replace("gate:\n", f"gate:\n  slices: {value}\n")
    with pytest.raises(ConfigError, match=r"gate\.slices"):
        load_config(write(tmp_path, text))
    with pytest.raises(ValidationError):
        GatePolicy.model_validate({"metrics": {}, "slices": 5})


def test_blank_slices_is_a_config_error(tmp_path: Path) -> None:
    text = MINIMAL.replace("gate:\n", "gate:\n  slices:\n")
    with pytest.raises(ConfigError, match=r"gate\.slices"):
        load_config(write(tmp_path, text))


@pytest.mark.parametrize("gate", ["5", "abc", "[1]", "null", ""])
def test_non_mapping_gate_is_a_config_error(gate: str, tmp_path: Path) -> None:
    head, _, rest = MINIMAL.partition("gate:\n")
    tail = rest[rest.index("budget:") :]
    with pytest.raises(ConfigError, match="gate"):
        load_config(write(tmp_path, f"{head}gate: {gate}\n{tail}"))


@pytest.mark.parametrize("value", HOSTILE)
@pytest.mark.parametrize("field", GATE_FIELDS)
def test_no_gate_field_value_escapes_as_anything_but_config_error(
    field: str, value: str, tmp_path: Path
) -> None:
    text = MINIMAL.replace("gate:\n", f"gate:\n  {field}: {value}\n")
    with contextlib.suppress(ConfigError):  # the only allowed failure; other types fail the test
        load_config(write(tmp_path, text))


def test_unknown_secret_looking_metric_key_is_not_echoed(tmp_path: Path) -> None:
    text = MINIMAL.replace(
        "    context_recall: {max_drop: 0.05}", "    api_key_sk-SECRET123: {max_drop: 0.05}"
    )
    with pytest.raises(ConfigError, match="unknown metric") as info:
        load_config(write(tmp_path, text))
    assert "SECRET123" not in str(info.value)


def test_model_copy_update_does_not_rederive_gated_slices() -> None:
    gate = GatePolicy(metrics={}, slices=("tenant",))
    assert gate.model_copy(update={"slices": ()}).gated_slices == gate.gated_slices
