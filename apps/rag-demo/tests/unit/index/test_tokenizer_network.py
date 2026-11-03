"""The pinned bge-m3 tokenizer downloaded for real (marker ``network``)."""

from pathlib import Path

import pytest
from rd_support import REPO

from rag_demo.index.fetch_tokenizer import fetch
from rag_demo.index.tokens import load_token_counter

pytestmark = pytest.mark.network


def test_real_bge_m3_tokenizer_matches_the_pin_and_counts_a_long_passage(tmp_path: Path) -> None:
    out = fetch(REPO / "infra" / "gpu" / "models.yaml", "ollama/bge-m3", tmp_path / "bge-m3.json")
    count = load_token_counter(out)
    assert 2 <= count("Kündigungsfrist") <= 8
    assert count(" ".join(["Arbeitnehmerkündigung"] * 2000)) > 1024
