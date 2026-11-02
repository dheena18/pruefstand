"""T3.1a CPU tests: catalogue tags against the names Ollama reports (``bge-m3:latest``).

The bodies have the shape of Ollama 0.32 (``name``, ``model``, ``digest``, ``size``, ``size_vram``,
``context_length``), as seen on the first real run: the embedding model's tag has no colon.
"""

import json

import gpu_catalogue as cat
from gpu_world import ENTRIES, GIB

BGE_DIGEST = ENTRIES["bge-m3"]["digest"]
JUDGE_DIGEST = ENTRIES["gemma3:12b"]["digest"]
GEN_DIGEST = ENTRIES["qwen3.8:27b-q8_0"]["digest"]


def _tags(*rows: tuple[str, str]) -> str:
    return json.dumps(
        {"models": [{"name": n, "model": n, "size": 1, "digest": d} for n, d in rows]}
    )


REAL_TAGS = _tags(
    ("bge-m3:latest", BGE_DIGEST), ("gemma3:12b", JUDGE_DIGEST), ("qwen3.8:27b-q8_0", GEN_DIGEST)
)


def _ps(*rows: tuple[str, str]) -> str:
    models = [
        {
            "name": n, "model": n, "size": 5 * GIB, "digest": d, "size_vram": 5 * GIB,
            "context_length": 1024, "expires_at": "2026-11-03T10:00:00Z", "details": {},
        }
        for n, d in rows
    ]  # fmt: skip
    return json.dumps({"models": models})


def test_a_tag_without_a_colon_matches_the_latest_name_ollama_reports() -> None:
    assert cat.tag_digest(REAL_TAGS, "bge-m3") == BGE_DIGEST
    assert cat.tag_digest(REAL_TAGS, "gemma3:12b") == JUDGE_DIGEST
    assert cat.tag_digest(REAL_TAGS, "qwen3.8:27b-q8_0") == GEN_DIGEST


def test_an_explicit_tag_still_matches_literally_and_another_tag_does_not() -> None:
    body = _tags(("bge-m3:other", "a" * 64), ("gemma3:12b", JUDGE_DIGEST))
    assert cat.tag_digest(body, "bge-m3") == ""  # bge-m3:other is not bge-m3:latest
    assert cat.tag_digest(body, "bge-m3:other") == "a" * 64
    assert cat.tag_digest(body, "gemma3:4b") == ""
    assert cat.tag_digest(body, "gemma3") == ""  # a catalogue tag "gemma3" would be gemma3:latest


def test_a_model_reported_without_the_latest_suffix_also_matches() -> None:
    assert cat.tag_digest(_tags(("bge-m3", BGE_DIGEST)), "bge-m3") == BGE_DIGEST


def test_ps_rows_name_resident_models_by_their_catalogue_tag() -> None:
    body = _ps(("bge-m3:latest", BGE_DIGEST), ("gemma3:12b", JUDGE_DIGEST))
    assert [r[0] for r in cat.ps_rows(body)] == ["bge-m3", "gemma3:12b"]


def test_ps_rows_keep_names_that_are_not_the_catalogue_tag() -> None:
    body = _ps(("bge-m3:other", "b" * 64), ("llama3:8b", "c" * 64), ("jeffh/x:f16", "d" * 64))
    assert [r[0] for r in cat.ps_rows(body)] == ["bge-m3:other", "llama3:8b", "jeffh/x:f16"]


def test_ps_rows_carry_context_size_and_vram_of_the_real_shape() -> None:
    row = cat.ps_rows(_ps(("bge-m3:latest", BGE_DIGEST)))[0]
    assert row == ("bge-m3", BGE_DIGEST, "1024", str(5 * GIB), str(5 * GIB))


def test_normalise_adds_latest_only_when_there_is_no_colon() -> None:
    assert cat.normalise("bge-m3") == "bge-m3:latest"
    assert cat.normalise("gemma3:12b") == "gemma3:12b"
    assert cat.normalise("jeffh/x:f16") == "jeffh/x:f16"
