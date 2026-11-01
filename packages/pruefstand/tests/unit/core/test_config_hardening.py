"""Round trips, hostile inputs and edge cases of the config layer (review of PR #7)."""

import contextlib
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from structlog.testing import capture_logs

from pruefstand.core.config import GatePolicy, MetricPolicy, PruefstandConfig, TargetConfig
from pruefstand.core.config_loader import MAX_CONFIG_DEPTH, load_config
from pruefstand.core.errors import ConfigError
from pruefstand.core.models_family import model_family

GEMMA = {"id": "ollama/gemma3:12b", "family": "gemma"}
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


# --- M1: GatePolicy survives dump / validate ---


@pytest.mark.parametrize(
    "slices",
    [(), ("category",), ("tenant",), ("lang", "tags"), ("category", "tenant", "lang")],
)
def test_gate_policy_round_trips(slices: tuple[str, ...]) -> None:
    gate = GatePolicy(metrics={"context_recall": MetricPolicy(max_drop=0.05)}, slices=slices)
    assert GatePolicy.model_validate(gate.model_dump()) == gate
    assert GatePolicy.model_validate_json(gate.model_dump_json()) == gate
    assert gate.model_copy() == gate
    assert isinstance(gate.gated_slices, tuple)


def test_default_gated_slices_follow_slices() -> None:
    assert GatePolicy(metrics={}, slices=()).gated_slices == ("overall", "perturbed_all")
    assert GatePolicy(metrics={}, slices=("lang",)).gated_slices == (
        "overall",
        "lang",
        "perturbed_all",
    )
    assert GatePolicy(metrics={}).gated_slices == ("overall", "tenant", "lang", "perturbed_all")
    assert GatePolicy(metrics={}, gated_slices=None).gated_slices == (  # type: ignore[arg-type]  # None means "derive"
        "overall",
        "tenant",
        "lang",
        "perturbed_all",
    )


def test_yaml_with_custom_slices_does_not_gate_uncomputed_slices(tmp_path: Path) -> None:
    text = MINIMAL.replace("gate:\n", "gate:\n  slices: [category]\n")
    cfg = load_config(write(tmp_path, text))
    assert cfg.gate.gated_slices == ("overall", "perturbed_all")
    assert PruefstandConfig.model_validate(cfg.model_dump()) == cfg


def test_explicit_gated_slice_outside_slices_still_fails() -> None:
    with pytest.raises(ConfigError, match="'tenant'"):
        GatePolicy(metrics={}, slices=("category",), gated_slices=("tenant",))


# --- M2: nesting depth ---


def test_deeply_nested_flow_sequence_is_a_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="nested deeper"):
        load_config(write(tmp_path, "[" * 500 + "]" * 500))


def test_deeply_nested_mappings_are_a_config_error(tmp_path: Path) -> None:
    depth = MAX_CONFIG_DEPTH + 1
    text = "".join("  " * i + f"k{i}:\n" for i in range(depth)) + "  " * depth + "v: 1\n"
    with pytest.raises(ConfigError, match="nested deeper"):
        load_config(write(tmp_path, text))


def test_ordinary_depth_is_fine(tmp_path: Path) -> None:
    assert load_config(write(tmp_path, MINIMAL)).splits


# --- m1: how the file is read ---


def test_dev_zero_and_directories_are_config_errors(tmp_path: Path) -> None:
    for target in (Path("/dev/zero"), tmp_path):
        with pytest.raises(ConfigError, match="regular file"):
            load_config(target)


def test_symlinks_are_refused(tmp_path: Path) -> None:
    real = write(tmp_path, MINIMAL)
    link = tmp_path / "link.yaml"
    link.symlink_to(real)
    with pytest.raises(ConfigError, match=r"cannot read|regular file"):
        load_config(link)


def test_invalid_utf8_is_a_config_error(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_bytes(b"version: \xff\xfe\n")
    with pytest.raises(ConfigError, match="UTF-8"):
        load_config(path)


def test_size_is_enforced_while_reading(tmp_path: Path) -> None:
    path = tmp_path / "big.yaml"
    path.write_bytes(b"#" * 1_000_001)
    with pytest.raises(ConfigError, match="too large"):
        load_config(path)


# --- m2: error messages never echo file content ---


def test_syntax_error_has_position_but_no_snippet(tmp_path: Path) -> None:
    path = write(tmp_path, "token: [sk-SECRET123\n")
    with pytest.raises(ConfigError, match=r"line 2") as info:
        load_config(path)
    assert "SECRET123" not in str(info.value)


def test_unknown_secret_looking_key_is_not_echoed(tmp_path: Path) -> None:
    path = write(tmp_path, MINIMAL + "token: sk-SECRET123\n")
    with pytest.raises(ConfigError) as info:
        load_config(path)
    assert "SECRET123" not in str(info.value)
    assert "token" not in str(info.value)


def test_unknown_plain_key_is_named_for_typos(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="seeed"):
        load_config(write(tmp_path, MINIMAL + "seeed: 1\n"))


# --- m3: numbers and duplicate keys ---


@pytest.mark.parametrize("bad", [".nan", ".inf"])
def test_non_finite_numbers_are_rejected(bad: str, tmp_path: Path) -> None:
    text = MINIMAL.replace("max_drop: 0.05", f"max_drop: {bad}")
    with pytest.raises(ConfigError, match="max_drop"):
        load_config(write(tmp_path, text))
    with pytest.raises(ValidationError):
        GatePolicy(metrics={}, alpha=float("nan"))
    with pytest.raises(ValidationError):
        TargetConfig(url="http://x", timeout_s=float("inf"))


def test_n_resamples_is_bounded() -> None:
    assert GatePolicy(metrics={}, n_resamples=10_000_000).n_resamples == 10_000_000
    with pytest.raises(ValidationError, match="n_resamples"):
        GatePolicy(metrics={}, n_resamples=10_000_001)


def test_duplicate_keys_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"line 3.*duplicate key"):
        load_config(write(tmp_path, "version: 1\nseed: 1\nseed: 2\n"))


def test_same_key_in_different_mappings_is_fine(tmp_path: Path) -> None:
    assert (
        load_config(write(tmp_path, MINIMAL)).judge.pr.id
        == load_config(write(tmp_path, MINIMAL)).judge.nightly.id
    )


# --- m4: families ---


@pytest.mark.parametrize(
    ("model_id", "family"),
    [
        ("ollama/qwq:32b", "qwen"),
        ("openrouter/alibaba/tongyi-deepresearch", "qwen"),
        ("ollama/ＱＷＥＮ3:8b", "qwen"),
        ("gemini/gemini-2.0-flash", "gemini"),
        ("gemini/gemma-3-27b-it", "gemma"),
    ],
)
def test_more_family_rows(model_id: str, family: str) -> None:
    assert model_family(model_id) == family


def test_declared_family_on_an_unrecognised_id_is_trusted() -> None:
    data: dict[str, Any] = {
        "version": 1,
        "target": {"url": "http://x"},
        "dataset": "d",
        "splits": ["smoke"],
        "generator_family": "qwen",
        "judge": {"pr": {"id": "ollama/mystery:1b", "family": "gemma"}, "nightly": GEMMA},
        "gate": {"metrics": {}},
        "budget": {},
        "runner": {},
        "baseline_store": {"type": "local_dir", "path": "b"},
    }
    assert PruefstandConfig.model_validate(data).judge.pr.family == "gemma"


# --- m6: url, hard_fail, per_metric ---


@pytest.mark.parametrize("url", ["ftp://x", "localhost:8000", "file:///etc/passwd", "http://", "x"])
def test_target_url_must_be_http_or_https(url: str) -> None:
    with pytest.raises(ValidationError, match="url"):
        TargetConfig(url=url)


@pytest.mark.parametrize("url", ["http://localhost:8000", "https://rag.example.org/v1"])
def test_http_urls_are_accepted(url: str) -> None:
    assert TargetConfig(url=url).url == url


def test_empty_hard_fail_is_allowed_but_warned() -> None:
    with capture_logs() as logs:
        gate = GatePolicy(metrics={}, hard_fail=())
    assert gate.hard_fail == ()
    assert any(entry.get("log_level") == "warning" for entry in logs)


def test_per_metric_judge_keys_must_be_judged_metrics() -> None:
    data: dict[str, Any] = {
        "version": 1,
        "target": {"url": "http://x"},
        "dataset": "d",
        "splits": ["smoke"],
        "generator_family": "qwen",
        "judge": {"pr": GEMMA, "nightly": GEMMA, "per_metric": {"context_recall": GEMMA}},
        "gate": {"metrics": {}},
        "budget": {},
        "runner": {},
        "baseline_store": {"type": "local_dir", "path": "b"},
    }
    with pytest.raises(ConfigError, match=r"per_metric\.context_recall.*judged"):
        PruefstandConfig.model_validate(data)


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
