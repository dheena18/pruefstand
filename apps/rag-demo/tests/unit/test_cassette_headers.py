"""Recorded cassettes name the model and weights SHA-256 they were recorded with (D353)."""

import re
from pathlib import Path

import pytest
import yaml
from rd_support import REPO

CASSETTES = Path(__file__).resolve().parents[1] / "cassettes"
LIVE_MODELS = yaml.safe_load((REPO / "infra" / "models" / "live-models.yaml").read_text("utf-8"))
HEADER = re.compile(r"^# recorded: \d{4}-\d{2}-\d{2}, git: [0-9a-f]+, (?P<model>.+), by ")


def _header(path: Path) -> re.Match[str] | None:
    return HEADER.match(path.read_text(encoding="utf-8").split("\n", 1)[0])


@pytest.mark.parametrize("path", sorted(CASSETTES.glob("generate_smoke_*.yaml")), ids=str)
def test_generator_cassette_header_has_the_pinned_model_id_and_sha256(path: Path) -> None:
    pinned = LIVE_MODELS["models"][0]
    match = _header(path)
    assert match, f"{path.name} has no `# recorded:` header with a model"
    model = pinned["id"].removesuffix(
        "-q4_k_m"
    )  # the id the llm cassettes carry (record_cassettes.sh)
    assert f"model: openai_compatible_local/{model}," in match["model"]
    assert f"sha256: {pinned['sha256']}" in match["model"]


@pytest.mark.parametrize("path", sorted(CASSETTES.glob("tei_*.yaml")), ids=str)
def test_embedding_cassette_header_has_the_pinned_model_revision_and_weights_sha256(
    path: Path,
) -> None:
    pinned = LIVE_MODELS["embeddings"][0]
    match = _header(path)
    assert match, f"{path.name} has no `# recorded:` header with a model"
    assert f"model: {pinned['repo']}@{pinned['revision']}" in match["model"]
    assert f"weights sha256: {pinned['weights_sha256']}" in match["model"]
