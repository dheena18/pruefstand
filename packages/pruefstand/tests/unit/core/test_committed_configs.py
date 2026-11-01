"""Committed-config rule (R9 X1.5): ``min_clusters >= 30`` in examples/** and apps/**/configs/**."""

from pathlib import Path

import pytest
import yaml

from pruefstand.core.config import PruefstandConfig
from pruefstand.core.config_loader import load_config
from pruefstand.core.enums import Split
from pruefstand.core.errors import ConfigError

ROOT = Path(__file__).resolve().parents[5]
MIN_CLUSTERS = 30


def committed_files(root: Path) -> list[Path]:
    """Gate-config candidates: yaml files under ``examples/`` and ``apps/**/configs/``."""
    found = [*sorted((root / "examples").rglob("*.y*ml"))]
    found += sorted((root / "apps").glob("**/configs/**/*.y*ml"))
    return [p for p in found if p.suffix in {".yaml", ".yml"}]


def is_gate_config(path: Path) -> bool:
    """True when the file is meant as a ``PruefstandConfig`` (has a top-level ``gate`` key).

    Other profiles, such as rag-demo's ``rag.yaml``, are skipped; a gate config that is broken
    is not skipped but reported by ``violations``.
    """
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return isinstance(data, dict) and "gate" in data


def violations(root: Path) -> list[str]:
    """Rule violations of every committed gate config under ``root``."""
    problems: list[str] = []
    for path in committed_files(root):
        if not is_gate_config(path):
            continue
        rel = path.relative_to(root)
        try:
            cfg: PruefstandConfig = load_config(path)
        except ConfigError as exc:
            problems.append(f"{rel}: does not load: {exc}")
            continue
        if cfg.gate.min_clusters < MIN_CLUSTERS:
            problems.append(f"{rel}: gate.min_clusters {cfg.gate.min_clusters} < {MIN_CLUSTERS}")
        if cfg.splits == (Split.SMOKE_LIVE,) and cfg.llm.fallback_judge is not None:
            problems.append(f"{rel}: tier-1 config must not set llm.fallback_judge (D97)")
    return problems


def test_repository_configs_follow_the_rules() -> None:
    assert violations(ROOT) == []


def test_the_live_example_is_checked() -> None:
    names = {p.name for p in committed_files(ROOT)}
    assert "pruefstand.yaml" in names
    assert all(is_gate_config(p) for p in committed_files(ROOT) if p.parent.name == "live")


def test_non_gate_profiles_are_skipped(tmp_path: Path) -> None:
    profile = tmp_path / "apps" / "rag-demo" / "configs" / "rag.yaml"
    profile.parent.mkdir(parents=True)
    profile.write_text("version: 1\ntop_k: 5\n", encoding="utf-8")
    assert violations(tmp_path) == []


def _small(tmp_path: Path, where: str) -> Path:
    text = (ROOT / "examples" / "live" / "pruefstand.yaml").read_text(encoding="utf-8")
    assert "min_clusters: 30" in text
    path = tmp_path / where
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.replace("min_clusters: 30", "min_clusters: 8"), encoding="utf-8")
    return path


def test_small_min_clusters_under_examples_fails_naming_the_file(tmp_path: Path) -> None:
    _small(tmp_path, "examples/x/small.yaml")
    problems = violations(tmp_path)
    assert len(problems) == 1
    assert "examples/x/small.yaml" in problems[0]
    assert "min_clusters" in problems[0]


def test_small_min_clusters_in_app_configs_fails(tmp_path: Path) -> None:
    _small(tmp_path, "apps/foo/configs/gate.yaml")
    assert any("apps/foo/configs/gate.yaml" in p for p in violations(tmp_path))


def test_test_only_fixture_configs_are_exempt(tmp_path: Path) -> None:
    _small(tmp_path, "packages/pruefstand/tests/fixtures/configs/small.yaml")
    assert violations(tmp_path) == []


def test_tier1_config_with_fallback_judge_fails(tmp_path: Path) -> None:
    path = _small(tmp_path, "examples/live/tier1.yaml")
    text = path.read_text(encoding="utf-8").replace("min_clusters: 8", "min_clusters: 30")
    text += "llm:\n  fallback_judge: {id: ollama/gemma3:4b, family: gemma}\n"
    path.write_text(text, encoding="utf-8")
    assert any("fallback_judge" in p for p in violations(tmp_path))


def test_broken_gate_config_is_reported_not_skipped(tmp_path: Path) -> None:
    path = tmp_path / "examples" / "broken.yaml"
    path.parent.mkdir(parents=True)
    path.write_text("gate: {metrics: {nonsense: {max_drop: 0.1}}}\n", encoding="utf-8")
    assert any("does not load" in p for p in violations(tmp_path))


@pytest.mark.parametrize("path", committed_files(ROOT), ids=lambda p: str(p.relative_to(ROOT)))
def test_each_committed_gate_config_loads(path: Path) -> None:
    if is_gate_config(path):
        assert load_config(path).gate.min_clusters >= MIN_CLUSTERS
