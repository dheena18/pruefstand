"""Pure request policy of llm-proxy on the real catalogue (interfaces 1.5; D206, D252, ADR-0018)."""

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from llm_proxy_policy import Forward, PolicyError, Reject, build_policy, decide, is_reload

ROOT = Path(__file__).resolve().parents[4]
CATALOGUE = yaml.safe_load((ROOT / "infra/gpu/models.yaml").read_text(encoding="utf-8"))["models"]
GEN, EMB, JUDGE = "qwen3.8:27b-q8_0", "bge-m3", "gemma3:12b"
KEY = "unit-test-key"
POLICY = build_policy(CATALOGUE, [GEN, EMB])
GEN_ENTRY = next(e for e in CATALOGUE if e["tag"] == GEN)


def _chat(model: object = GEN, **extra: Any) -> bytes:
    body = {
        "model": model,
        "messages": [{"role": "user", "content": "Was regelt § 573 BGB zur Kündigung?"}],
    }
    return json.dumps({**body, **extra}, ensure_ascii=False).encode()


def _decide(
    method: str, path: str, body: bytes = b"", auth: str | None = f"Bearer {KEY}"
) -> Forward | Reject:
    return decide(method, path, auth=auth, body=body, key=KEY, policy=POLICY)


def _forwarded(body: bytes, path: str = "/api/chat") -> dict[str, Any]:
    verdict = _decide("POST", path, body)
    assert isinstance(verdict, Forward), verdict
    assert verdict.body is not None
    out: dict[str, Any] = json.loads(verdict.body)
    return out


def test_allowed_routes_are_forwarded() -> None:
    assert isinstance(_decide("POST", "/api/chat", _chat()), Forward)
    embed = json.dumps({"model": EMB, "input": ["Mietrecht"]}).encode()
    assert isinstance(_decide("POST", "/api/embed", embed), Forward)
    assert _decide("GET", "/api/tags") == Forward("GET", "/api/tags", None)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/v1/chat/completions"),
        ("POST", "/v1/embeddings"),
        ("POST", "/api/pull"),
        ("DELETE", "/api/delete"),
        ("POST", "/api/delete"),
        ("POST", "/api/create"),
        ("POST", "/api/copy"),
        ("POST", "/api/generate"),
        ("GET", "/api/ps"),
        ("GET", "/api/tags?x=1"),
        ("POST", "/api/chat/../pull"),
        ("GET", "/api/chat"),
    ],
)
def test_other_paths_are_rejected(method: str, path: str) -> None:
    verdict = _decide(method, path, _chat())
    assert isinstance(verdict, Reject)
    assert verdict.status == 403


@pytest.mark.parametrize("auth", [None, "", "Bearer wrong", f"bearer {KEY}", KEY, f"Bearer {KEY} "])
def test_missing_or_wrong_key_is_rejected(auth: str | None) -> None:
    assert _decide("POST", "/api/chat", _chat(), auth=auth) == Reject(
        403, "missing or wrong bearer key"
    )


def test_empty_configured_key_rejects_everything() -> None:
    verdict = decide("GET", "/api/tags", auth="Bearer ", body=b"", key="", policy=POLICY)
    assert isinstance(verdict, Reject)


@pytest.mark.parametrize("model", [JUDGE, "qwen3:4b", "llama3:8b", "", None])
def test_judge_and_unknown_models_are_rejected(model: str | None) -> None:
    assert _decide("POST", "/api/chat", _chat(model=model)) == Reject(403, "model not allowed")


def test_role_must_match_route() -> None:
    embed_on_chat = _decide("POST", "/api/chat", _chat(model=EMB))
    chat_on_embed = _decide("POST", "/api/embed", json.dumps({"model": GEN, "input": "x"}).encode())
    assert isinstance(embed_on_chat, Reject)
    assert isinstance(chat_on_embed, Reject)


@pytest.mark.parametrize("body", [b"not json", b"[1, 2]", b"\xff\xfe"])
def test_non_object_bodies_are_rejected(body: bytes) -> None:
    assert isinstance(_decide("POST", "/api/chat", body), Reject)


def test_num_ctx_enforced_load_time_keys_dropped_sampling_kept() -> None:
    body = _chat(options={"num_ctx": 65536, "num_gpu": 0, "temperature": 0.9, "mirostat": 2})
    options = _forwarded(body)["options"]
    assert options["num_ctx"] == GEN_ENTRY["options"]["num_ctx"]
    assert "num_gpu" not in options
    assert "mirostat" not in options
    assert options["temperature"] == 0.9


def test_seed_top_p_num_predict_pass_unchanged() -> None:
    options = _forwarded(_chat(options={"seed": 7, "top_p": 0.5, "num_predict": 200}))["options"]
    assert (options["seed"], options["top_p"], options["num_predict"]) == (7, 0.5, 200)


def test_missing_options_get_catalogue_values() -> None:
    options = _forwarded(_chat())["options"]
    assert options == GEN_ENTRY["options"]


@pytest.mark.parametrize(
    ("options", "name"),
    [
        ({"temperature": 1.5}, "temperature"),
        ({"num_predict": GEN_ENTRY["options"]["num_predict"] + 1}, "num_predict"),
        ({"num_predict": 0}, "num_predict"),
        ({"top_p": -0.1}, "top_p"),
        ({"temperature": "hot"}, "temperature"),
        ({"temperature": True}, "temperature"),
        ({"seed": 1.5}, "seed"),
    ],
)
def test_out_of_bounds_options_are_rejected(options: dict[str, Any], name: str) -> None:
    assert _decide("POST", "/api/chat", _chat(options=options)) == Reject(
        403, f"option out of bounds: {name}"
    )


@pytest.mark.parametrize("keep_alive", [0, "0", -1, "24h"])
def test_keep_alive_is_stripped(keep_alive: object) -> None:
    assert "keep_alive" not in _forwarded(_chat(keep_alive=keep_alive))


def test_embed_without_bounds_keeps_catalogue_defaults() -> None:
    body = json.dumps(
        {"model": EMB, "input": "Kündigung", "options": {"temperature": 0.7}}
    ).encode()
    options = _forwarded(body, "/api/embed")["options"]
    emb = next(e for e in CATALOGUE if e["tag"] == EMB)["options"]
    assert options["num_ctx"] == emb["num_ctx"]
    assert options["temperature"] == emb["temperature"]


def test_other_body_fields_pass_unchanged() -> None:
    out = _forwarded(_chat(think=False, stream=False, format="json"))
    assert (out["think"], out["stream"], out["format"]) == (False, False, "json")
    assert out["messages"][0]["content"].endswith("Kündigung?")


@pytest.mark.parametrize("tag", [JUDGE, "nicht-im-katalog"])
def test_build_policy_refuses_judges_and_unknown_tags(tag: str) -> None:
    with pytest.raises(PolicyError):
        build_policy(CATALOGUE, [GEN, tag])


def test_build_policy_needs_integer_num_ctx_and_valid_bounds() -> None:
    entry = {"tag": "x", "role": "generator", "options": {"temperature": 0.0}}
    with pytest.raises(PolicyError, match="num_ctx"):
        build_policy([entry], ["x"])
    bad = {**entry, "options": {"num_ctx": 8}, "option_bounds": {"temperature": [1.0, 0.0]}}
    with pytest.raises(PolicyError, match="low, high"):
        build_policy([bad], ["x"])
    with pytest.raises(PolicyError, match="number"):
        build_policy([{**entry, "options": {"num_ctx": "8"}}], ["x"])


def test_policy_holds_exactly_the_run_tags() -> None:
    assert set(POLICY) == {GEN, EMB}


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (b'{"load_duration": 2500000000}', True),
        (b'{"load_duration": 200000000}', False),
        (b'{"done": false}\n{"done": true, "load_duration": 1500000000}\n', True),
        (b"kein json", False),
        (b"[]", False),
    ],
)
def test_is_reload(payload: bytes, expected: bool) -> None:  # noqa: FBT001 - parametrized
    assert is_reload(payload) is expected
