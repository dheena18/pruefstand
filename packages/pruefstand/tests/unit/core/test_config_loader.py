import re
from pathlib import Path

import pytest
import yaml

from pruefstand.core.config import PruefstandConfig
from pruefstand.core.config_loader import MAX_CONFIG_BYTES, load_config
from pruefstand.core.enums import Split
from pruefstand.core.errors import ConfigError

ROOT = Path(__file__).resolve().parents[5]
SPEC = ROOT / "docs" / "spec" / "SPEC.md"

MINIMAL = """\
version: 1
target: {type: http, url: "http://localhost:8000"}
dataset: datasets/fixtures/slice_v1
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


def write(tmp_path: Path, text: str, name: str = "pruefstand.yaml") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def spec_block() -> str:
    text = SPEC.read_text(encoding="utf-8")
    start = text.index("### 5.6 Gate config")
    match = re.search(r"```yaml\n(.*?)\n```", text[start:], re.DOTALL)
    assert match is not None
    return match.group(1)


def test_minimal_config_loads(tmp_path: Path) -> None:
    cfg = load_config(write(tmp_path, MINIMAL))
    assert isinstance(cfg, PruefstandConfig)
    assert cfg.splits == (Split.SMOKE,)


def test_live_example_loads() -> None:
    cfg = load_config(ROOT / "examples" / "live" / "pruefstand.yaml")
    assert cfg.splits == (Split.SMOKE_LIVE,)
    assert cfg.generator_family == "qwen"
    assert cfg.llm.fallback_judge is None
    assert cfg.budget.max_requests_per_run == 10
    assert cfg.runner.concurrency == 2
    assert "error_rate" in cfg.gate.metrics
    assert "ndcg_at_k" in cfg.gate.metrics
    judged = {"faithfulness", "answer_correctness", "perturbation_consistency", "refusal_judged"}
    assert judged <= set(cfg.gate.metrics)  # informational in tier 1 (T5.2b)
    assert cfg.gate.metrics["injection_success"].max_value == 0.02
    assert cfg.gate.metrics["refusal_correct"].max_drop == 0.10


def test_root_example_loads() -> None:
    assert load_config(ROOT / "pruefstand.yaml").gate.min_clusters >= 30


def test_spec_section_5_6_block_loads(tmp_path: Path) -> None:
    cfg = load_config(write(tmp_path, spec_block()))
    assert cfg.gate.metrics["ndcg_at_k"].max_drop == 0.05
    assert cfg.baseline_store.type == "local_dir"
    assert cfg.baseline_store.path is not None
    assert cfg.splits == (Split.SMOKE, Split.CORE, Split.ROBUST_PR)
    assert cfg.gate.metrics["injection_success"].max_value == 0.02


def test_citation_grounded_is_accepted(tmp_path: Path) -> None:
    text = MINIMAL.replace(
        "    context_recall: {max_drop: 0.05}",
        "    context_recall: {max_drop: 0.05}\n    citation_grounded: {max_drop: 0.05}",
    )
    assert "citation_grounded" in load_config(write(tmp_path, text)).gate.metrics


def test_wrong_type_error_carries_the_yaml_path(tmp_path: Path) -> None:
    text = MINIMAL.replace(
        "    context_recall: {max_drop: 0.05}",
        "    citation_f1: {max_drop: x}",
    )
    with pytest.raises(ConfigError, match=r"gate\.metrics\.citation_f1\.max_drop"):
        load_config(write(tmp_path, text))


def test_all_errors_are_reported_at_once(tmp_path: Path) -> None:
    text = MINIMAL.replace("splits: [smoke]", "splits: [nope]") + "seed: abc\n"
    with pytest.raises(ConfigError) as info:
        load_config(write(tmp_path, text))
    message = str(info.value)
    assert "splits.0" in message
    assert "seed" in message
    assert str(tmp_path / "pruefstand.yaml") in message


def test_system_prompt_similarity_is_never_gated(tmp_path: Path) -> None:
    text = MINIMAL.replace(
        "    context_recall: {max_drop: 0.05}",
        "    context_recall: {max_drop: 0.05}\n    system_prompt_similarity: {max_value: 0.5}",
    )
    with pytest.raises(ConfigError, match="system_prompt_similarity"):
        load_config(write(tmp_path, text))


def test_evidence_recall_is_an_unknown_metric(tmp_path: Path) -> None:
    text = MINIMAL.replace(
        "    context_recall: {max_drop: 0.05}",
        "    context_recall: {max_drop: 0.05}\n    evidence_recall: {max_drop: 0.05}",
    )
    with pytest.raises(ConfigError, match=r"gate\.metrics\.evidence_recall.*unknown"):
        load_config(write(tmp_path, text))


def test_family_error_is_prefixed_with_the_file(tmp_path: Path) -> None:
    text = MINIMAL.replace(
        'pr: {id: "ollama/gemma3:12b", family: gemma}',
        'pr: {id: "ollama/qwen3:8b", family: qwen}',
    )
    path = write(tmp_path, text)
    with pytest.raises(ConfigError, match="ADR-0009") as info:
        load_config(path)
    assert str(path) in str(info.value)


def test_file_over_one_megabyte_is_rejected(tmp_path: Path) -> None:
    path = write(tmp_path, MINIMAL + "# " + "x" * (MAX_CONFIG_BYTES + 10) + "\n")
    assert path.stat().st_size > MAX_CONFIG_BYTES
    with pytest.raises(ConfigError, match="too large"):
        load_config(path)


def test_python_object_tag_is_rejected(tmp_path: Path) -> None:
    text = MINIMAL + "evil: !!python/object/apply:os.system ['true']\n"
    with pytest.raises(ConfigError, match="YAML"):
        load_config(write(tmp_path, text))


def test_yaml_aliases_are_rejected(tmp_path: Path) -> None:
    text = MINIMAL.replace(
        "context_recall: {max_drop: 0.05}",
        "context_recall: &p {max_drop: 0.05}\n    ndcg_at_k: *p",
    )
    with pytest.raises(ConfigError, match="alias"):
        load_config(write(tmp_path, text))


@pytest.mark.parametrize("text", ["", "- a\n- b\n", "just a string\n"])
def test_non_mapping_documents_are_rejected(tmp_path: Path, text: str) -> None:
    with pytest.raises(ConfigError, match="mapping"):
        load_config(write(tmp_path, text))


def test_invalid_yaml_syntax_is_a_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="invalid YAML"):
        load_config(write(tmp_path, "a: [unclosed\n"))


def test_missing_file_is_a_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="cannot read"):
        load_config(tmp_path / "nope.yaml")


def test_env_interpolation_is_not_performed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PRUEFSTAND_DATA_ROOT", "/secret/place")
    text = MINIMAL.replace("path: baselines", 'path: "${PRUEFSTAND_DATA_ROOT}/baselines"')
    cfg = load_config(write(tmp_path, text))
    assert cfg.baseline_store.path == Path("${PRUEFSTAND_DATA_ROOT}/baselines")


def test_spec_block_is_valid_yaml_mapping() -> None:
    assert isinstance(yaml.safe_load(spec_block()), dict)
