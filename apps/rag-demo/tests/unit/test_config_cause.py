"""T6.3 S4: the five tier-2 cause-switch scenarios are rag.gpu.yaml plus exactly their switch."""

from typing import Any

import pytest
import yaml
from rd_support import CONFIGS, REPO

from rag_demo.config import config_hash, load_config

CATALOGUE = REPO / "infra" / "gpu" / "models.yaml"
GPU = CONFIGS / "rag.gpu.yaml"
CAUSE = CONFIGS / "cause"
SWITCHES = {
    "retrieval_reranker_off_top3": {"reranker", "top_k"},
    "no_citations": {"prompt_file"},
    "answer_language_en": {"answer_language"},
    "no_refusal": {"prompt_file"},
    "errors_closed_port": {"generator.endpoint_env", "generator.base_url"},
}
SAME_AS_GPU_BUG = ("no_citations", "answer_language_en", "no_refusal")  # T1.13's switch, tier 2


def _flat(data: dict[str, Any], prefix: str = "") -> dict[str, object]:
    out: dict[str, object] = {}
    for key, value in data.items():
        if isinstance(value, dict):
            out.update(_flat(value, f"{prefix}{key}."))
        else:
            out[f"{prefix}{key}"] = value
    return out


def _load(path: Any) -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data


def test_the_five_scenarios_exist_and_nothing_else() -> None:
    assert {p.stem for p in CAUSE.glob("*.yaml")} == set(SWITCHES)


@pytest.mark.parametrize(("name", "fields"), sorted(SWITCHES.items()))
def test_each_scenario_differs_from_rag_gpu_in_its_switch_only(name: str, fields: set[str]) -> None:
    good, case = _flat(_load(GPU)), _flat(_load(CAUSE / f"{name}.yaml"))
    assert {k for k in good.keys() | case.keys() if good.get(k) != case.get(k)} == fields
    cfg = load_config(CAUSE / f"{name}.yaml", catalogue_path=CATALOGUE)
    assert config_hash(cfg) != config_hash(load_config(GPU, catalogue_path=CATALOGUE))


@pytest.mark.parametrize("name", SAME_AS_GPU_BUG)
def test_the_middle_three_equal_the_matching_gpu_bug_config(name: str) -> None:
    assert _load(CAUSE / f"{name}.yaml") == _load(CONFIGS / "bugs" / "gpu" / f"{name}.yaml")


def test_the_errors_scenario_points_the_generator_at_a_closed_local_port() -> None:
    gen = load_config(CAUSE / "errors_closed_port.yaml", catalogue_path=CATALOGUE).generator
    assert gen.base_url == "http://127.0.0.1:9"
    assert gen.endpoint_env is None  # never llm-proxy, so it is a candidate error, not infra (D226)


def test_the_scenarios_are_not_gate_configs() -> None:
    for path in CAUSE.glob("*.yaml"):
        data = _load(path)
        assert "version" not in data
        assert "target" not in data
