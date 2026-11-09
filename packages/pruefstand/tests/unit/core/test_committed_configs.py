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
QUEUE_WAIT_S = 300  # D624: rag-demo read timeout; the A40 generator serialises requests


def committed_files(root: Path) -> list[Path]:
    """Gate-config candidates: yaml files under ``examples/`` and ``apps/**/configs/``."""
    found = [*sorted((root / "examples").rglob("*.y*ml"))]
    found += sorted((root / "apps").glob("**/configs/**/*.y*ml"))
    return [p for p in found if p.suffix in {".yaml", ".yml"}]


def is_gate_config(path: Path) -> bool:
    """True when the file is meant as a ``PruefstandConfig`` (top-level ``version`` and ``target``).

    Other profiles, such as rag-demo's ``rag.yaml``, are skipped. A gate config that is broken or
    lacks ``gate`` is not skipped: ``violations`` reports that it does not load.
    """
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return isinstance(data, dict) and "version" in data and "target" in data


def tier2_runner_ok(cfg: PruefstandConfig) -> bool:
    """D624: the A40 generator serialises requests, so a request can queue for minutes.

    The runner must outwait the read timeout of rag-demo (``timeout_s`` > 300) or send at most
    four requests at once; otherwise the runner gives up first. rag-demo cancels the upstream call
    when the runner disconnects (T3.6a); not retrying a read timeout is the runner's part (T6.2a).
    """
    return cfg.runner.timeout_s > QUEUE_WAIT_S or cfg.runner.concurrency <= 4


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
        if Split.CORE in cfg.splits and not tier2_runner_ok(cfg):
            problems.append(
                f"{rel}: tier-2 runner needs timeout_s > {QUEUE_WAIT_S} or concurrency <= 4 (D624)"
            )
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


def test_gate_config_without_gate_block_fails_not_skips(tmp_path: Path) -> None:
    text = (ROOT / "examples" / "live" / "pruefstand.yaml").read_text(encoding="utf-8")
    start, end = text.index("\ngate:"), text.index("\nbudget:")
    path = tmp_path / "examples" / "nogate.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(text[:start] + text[end:], encoding="utf-8")
    assert any("does not load" in p for p in violations(tmp_path))


def test_root_pruefstand_yaml_loads_with_enough_clusters() -> None:
    assert load_config(ROOT / "pruefstand.yaml").gate.min_clusters >= MIN_CLUSTERS


def test_broken_gate_config_is_reported_not_skipped(tmp_path: Path) -> None:
    path = tmp_path / "examples" / "broken.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(
        "version: 1\ntarget: {url: http://x}\ngate: {metrics: {nonsense: {max_drop: 0.1}}}\n",
        encoding="utf-8",
    )
    assert any("does not load" in p for p in violations(tmp_path))


@pytest.mark.parametrize("path", committed_files(ROOT), ids=lambda p: str(p.relative_to(ROOT)))
def test_each_committed_gate_config_loads(path: Path) -> None:
    if is_gate_config(path):
        assert load_config(path).gate.min_clusters >= MIN_CLUSTERS


def _tier2(tmp_path: Path, runner: str) -> Path:
    text = (ROOT / "examples" / "live" / "pruefstand.yaml").read_text(encoding="utf-8")
    text = text.replace("splits: [smoke_live]", "splits: [smoke, core]")
    assert "splits: [smoke, core]" in text
    start, end = text.index("\nrunner:"), text.index("\nbaseline_store:")
    path = tmp_path / "examples" / "tier2.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(text[:start] + "\nrunner: " + runner + text[end:], encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("runner", "ok"),
    [
        ("{concurrency: 8, timeout_s: 60, max_retries: 3}", False),
        ("{concurrency: 8, timeout_s: 300, max_retries: 3}", False),
        ("{concurrency: 8, timeout_s: 330, max_retries: 0}", True),
        ("{concurrency: 4, timeout_s: 60, max_retries: 0}", True),
    ],
)
def test_tier2_runner_must_outwait_the_generator_queue(
    tmp_path: Path, runner: str, *, ok: bool
) -> None:
    _tier2(tmp_path, runner)
    assert (violations(tmp_path) == []) is ok
