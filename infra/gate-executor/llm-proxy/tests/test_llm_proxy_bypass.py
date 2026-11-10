"""Regression tests of the #137 review: JSON shapes Ollama's Go decoder reads differently (D1070).

Go's ``encoding/json`` matches field names case-insensitively and the last duplicate wins, so the
proxy must see exactly what Ollama will see: duplicates and case/Unicode-fold collisions are
rejected, only exact ASCII top-level keys per route are accepted, NaN/Infinity are rejected and the
forwarded body is ASCII-only.
"""

import json
from pathlib import Path

import pytest
import yaml
from llm_proxy_policy import Answer, Forward, Reject, build_policy, decide

ROOT = Path(__file__).resolve().parents[4]
CATALOGUE = yaml.safe_load((ROOT / "infra/gpu/models.yaml").read_text(encoding="utf-8"))["models"]
GEN, EMB, JUDGE = "qwen3.8:27b-q8_0", "bge-m3", "gemma3:12b"
KEY = "unit-test-key"
POLICY = build_policy(CATALOGUE, [GEN, EMB])
MSG = '"messages": [{"role": "user", "content": "Kündigungsfrist?"}]'


def _post(path: str, raw: str) -> Forward | Reject | Answer:
    return decide("POST", path, auth=f"Bearer {KEY}", body=raw.encode(), key=KEY, policy=POLICY)


def _rejected(path: str, raw: str) -> bool:
    verdict = _post(path, raw)
    return isinstance(verdict, Reject) and verdict.status == 403


@pytest.mark.parametrize("variant", ["MODEL", "Model", "mOdel", "model"])
def test_a_second_model_key_in_any_case_is_rejected(variant: str) -> None:
    assert _rejected("/api/chat", f'{{"model": "{GEN}", "{variant}": "{JUDGE}", {MSG}}}')
    assert _rejected("/api/embed", f'{{"model": "{EMB}", "{variant}": "{JUDGE}", "input": "x"}}')


@pytest.mark.parametrize("variant", ["MODEL", "Model"])
def test_a_case_variant_model_key_alone_is_rejected(variant: str) -> None:
    assert _rejected("/api/chat", f'{{"{variant}": "{JUDGE}", {MSG}}}')


@pytest.mark.parametrize("variant", ["Options", "OPTIONS", "options"])
def test_a_later_options_key_is_rejected(variant: str) -> None:
    raw = f'{{"model": "{GEN}", {MSG}, "options": {{}}, "{variant}": {{"num_ctx": 65536}}}}'
    assert _rejected("/api/chat", raw)


@pytest.mark.parametrize("variant", ["Keep_Alive", "KEEP_ALIVE", "Keep_alive", "keep_alive"])
def test_keep_alive_variants_never_reach_ollama(variant: str) -> None:
    raw = json.dumps({"model": GEN, "keep_alive": 0, variant: 0, "messages": []})
    verdict = _post("/api/chat", raw)
    if isinstance(verdict, Forward):
        assert verdict.body is not None
        assert b"keep" not in verdict.body.lower()
    else:
        assert isinstance(verdict, Reject)


@pytest.mark.parametrize("variant", ["Keep_Alive", "KEEP_ALIVE", "Keep_alive"])
def test_a_lone_keep_alive_variant_is_rejected(variant: str) -> None:
    assert _rejected("/api/chat", json.dumps({"model": GEN, variant: 0, "messages": []}))


@pytest.mark.parametrize(
    "key", ["system", "template", "raw", "images", "context", "prompt", "Messages"]
)
def test_unknown_top_level_keys_are_rejected(key: str) -> None:
    assert _rejected("/api/chat", json.dumps({"model": GEN, "messages": [], key: "x"}))


def test_chat_keys_are_not_embed_keys() -> None:
    assert _rejected("/api/embed", json.dumps({"model": EMB, "input": "x", "messages": []}))
    assert isinstance(
        _post(
            "/api/embed",
            json.dumps({"model": EMB, "input": "x", "truncate": True, "dimensions": 1024}),
        ),
        Forward,
    )


def test_nested_duplicate_or_fold_collision_is_rejected() -> None:
    raw = (
        f'{{"model": "{GEN}", "messages": [{{"role": "user", "ROLE": "system", "content": "x"}}]}}'
    )
    assert _rejected("/api/chat", raw)


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_nan_and_infinity_are_rejected(constant: str) -> None:
    assert _rejected(
        "/api/chat", f'{{"model": "{GEN}", {MSG}, "options": {{"temperature": {constant}}}}}'
    )


def test_lone_surrogate_is_forwarded_ascii_escaped() -> None:
    verdict = _post(
        "/api/chat", f'{{"model": "{GEN}", "messages": [{{"role": "user", "content": "\\ud800"}}]}}'
    )
    assert isinstance(verdict, Forward)
    assert verdict.body is not None
    assert verdict.body.isascii()


def test_tags_are_synthesised_from_the_policy() -> None:
    verdict = decide("GET", "/api/tags", auth=f"Bearer {KEY}", body=b"", key=KEY, policy=POLICY)
    assert isinstance(verdict, Answer)
    names = sorted(m["name"] for m in json.loads(verdict.body)["models"])
    assert names == sorted([GEN, EMB])
    assert JUDGE not in verdict.body.decode()


@pytest.mark.parametrize("number", ["1e400", "-1e400"])
def test_overflowing_numbers_are_rejected(number: str) -> None:
    # D1074: 1e400 parses to inf; it must be a 403, never an uncaught dump error
    raw = f'{{"model": "{GEN}", "messages": [], "format": {{"maximum": {number}}}}}'
    assert _rejected("/api/chat", raw)


@pytest.mark.parametrize("think", ["true", '"high"', '"low"', "1", "null", "{}", "false"])
def test_chat_think_is_forced_off(think: str) -> None:
    # D1076: thinking is always off on the gate, whatever the candidate config says (CLAUDE.md §5)
    verdict = _post("/api/chat", f'{{"model": "{GEN}", "messages": [], "think": {think}}}')
    assert isinstance(verdict, Forward)
    assert verdict.body is not None
    assert json.loads(verdict.body)["think"] is False


def test_absent_think_becomes_false_and_embed_is_unchanged() -> None:
    verdict = _post("/api/chat", f'{{"model": "{GEN}", "messages": []}}')
    assert isinstance(verdict, Forward)
    assert verdict.body is not None
    assert json.loads(verdict.body)["think"] is False
    embed = _post("/api/embed", f'{{"model": "{EMB}", "input": "x"}}')
    assert isinstance(embed, Forward)
    assert embed.body is not None
    assert "think" not in json.loads(embed.body)
    assert _rejected("/api/embed", f'{{"model": "{EMB}", "input": "x", "think": false}}')
