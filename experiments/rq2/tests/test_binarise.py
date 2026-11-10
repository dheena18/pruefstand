"""T5.4 S2: binarisation (judge 2 vs < 2) and the MEMERAG routing guard."""

import pytest
from rq2.binarise import binary_pairs, check_route

from pruefstand.core.errors import ConfigError


def test_three_point_scores_are_binarised_against_the_labels() -> None:
    pairs = binary_pairs("answer_correctness", [2, 1, 0], [2, 0, 0])
    assert pairs == [(1, 1), (0, 0), (0, 0)]


def test_memerag_rows_are_never_routed_to_a_github_judge() -> None:
    path = "data/derived/memerag_de/faithfulness_memerag.jsonl"
    with pytest.raises(ConfigError, match="local judges only"):
        check_route("github/openai/gpt-4.1-mini", "memerag", path, local_only=True)
    with pytest.raises(ConfigError):
        check_route("github/openai/gpt-4.1-mini", "x", path, local_only=False)
    check_route("ollama/gemma3:12b", "memerag", path, local_only=True)
    check_route(
        "github/openai/gpt-4.1-mini",
        "refusal",
        "datasets/calibration/v1/refusal.jsonl",
        local_only=False,
    )
