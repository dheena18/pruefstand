"""contamination-probe phase (T4.6 S7, D1099): main's generator from the real configs, argv."""

from pathlib import Path

import pytest
import yaml
from gate_orchestrator.cmd_nightly import _inform
from gate_orchestrator.nightly_probe import probe_argv, probe_model

REPO = Path(__file__).resolve().parents[4]


def test_the_probe_asks_mains_tier2_generator_from_the_catalogue(tmp_path: Path) -> None:
    argv = probe_argv(REPO, tmp_path)
    rag = yaml.safe_load((REPO / "apps/rag-demo/configs/rag.gpu.yaml").read_text("utf-8"))
    assert argv[:2] == ["python", str(REPO / "scripts" / "contamination_probe.py")]
    assert argv[argv.index("--model") + 1] == rag["generator"]["catalogue_id"]
    assert argv[argv.index("--family") + 1] == "qwen"
    assert argv[-2:] == ["--out-dir", str(tmp_path)]


@pytest.mark.parametrize(
    "rag",
    [{"generator": {"catalogue_id": "ollama/gemma3:12b"}}, {"generator": {}}, {}],
)
def test_a_generator_outside_the_catalogue_generators_is_refused(rag: dict[str, object]) -> None:
    catalogue = yaml.safe_load((REPO / "infra/gpu/models.yaml").read_text("utf-8"))
    with pytest.raises(ValueError, match="not a catalogue generator"):
        probe_model(rag, catalogue)


def test_a_broken_probe_config_is_reported_and_never_fails_the_night(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _inform(lambda: probe_argv(tmp_path / "no-main", tmp_path), {})
    assert "informational phase not run" in capsys.readouterr().out
