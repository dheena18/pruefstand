"""OllamaDenseEncoder against the native ``/api/embed`` API (respx plumbing, T3.4).

Request shape (bare tag, catalogue options, no keep_alive), batching, retries, the bearer header
(D216) and the truncation counter; the vectors of the real model are covered by the `gpu` test.
"""

import json
import logging
from pathlib import Path

import httpx
import numpy as np
import pytest
import respx
from rd_support import REPO, write_word_tokenizer

from rag_demo.catalogue import load_catalogue
from rag_demo.errors import ConfigError, EncoderError
from rag_demo.index.encoders import OllamaDenseEncoder
from rag_demo.index.tokens import load_token_counter
from rag_demo.models import EmbedCfg

ENV = "PRUEFSTAND_CANDIDATE_API_KEY"
OLLAMA = "http://ollama.test:11434"

BGE = EmbedCfg(
    model="bge-m3",
    engine="ollama",
    catalogue_id="ollama/bge-m3",
    endpoint_env="OLLAMA_GPU0_URL",
    max_input_tokens=1024,
    dim=1024,
    options={"num_ctx": 1024},
)
CATALOGUE_OPTIONS = {
    k: (int(v) if k in {"num_ctx", "num_predict", "seed"} else v)
    for k, v in load_catalogue(REPO / "infra" / "gpu" / "models.yaml")[
        "ollama/bge-m3"
    ].options.items()
}


def _no_sleep(_seconds: float) -> None:
    return None


def _ollama_route(dim: int = 1024) -> respx.Route:
    def reply(req: httpx.Request) -> httpx.Response:
        n = len(json.loads(req.content)["input"])
        return httpx.Response(200, json={"embeddings": [[3.0] + [4.0] * (dim - 1)] * n})

    return respx.post(f"{OLLAMA}/api/embed").mock(side_effect=reply)


def _body(route: respx.Route) -> dict[str, object]:
    return json.loads(route.calls.last.request.content)  # type: ignore[no-any-return]  # json


@pytest.fixture(scope="module")
def word_tokenizer(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A real `tokenizers` word-level tokenizer file (one token per word)."""
    return write_word_tokenizer(tmp_path_factory.mktemp("tok") / "tokenizer.json")


@respx.mock
def test_ollama_request_is_native_api_embed_with_catalogue_options() -> None:
    route = _ollama_route()
    OllamaDenseEncoder(BGE, OLLAMA, options=CATALOGUE_OPTIONS).encode(["Kündigung"], kind="passage")
    request = route.calls.last.request
    assert request.url.path == "/api/embed"
    assert "/v1" not in request.url.path
    body = _body(route)
    assert body["model"] == "bge-m3"  # the bare tag, not ollama/bge-m3
    assert body["input"] == ["Kündigung"]
    assert body["truncate"] is True
    assert body["options"] == CATALOGUE_OPTIONS
    assert body["options"]["num_ctx"] == BGE.max_input_tokens
    assert "keep_alive" not in body


@respx.mock
def test_ollama_without_catalogue_options_sends_the_config_options() -> None:
    route = _ollama_route()
    OllamaDenseEncoder(BGE, OLLAMA).encode(["x"])
    assert _body(route)["options"] == {"num_ctx": 1024}


def test_ollama_num_ctx_must_equal_max_input_tokens() -> None:
    with pytest.raises(ConfigError, match="num_ctx"):
        OllamaDenseEncoder(BGE, OLLAMA, options={"num_ctx": 8192})
    with pytest.raises(ConfigError, match="num_ctx"):
        OllamaDenseEncoder(BGE, OLLAMA, options={})


@respx.mock
def test_ollama_70_texts_are_3_requests_and_vectors_are_unit_norm() -> None:
    route = _ollama_route()
    out = OllamaDenseEncoder(BGE, OLLAMA).encode([f"t{i}" for i in range(70)], kind="passage")
    assert route.call_count == 3
    assert out.shape == (70, 1024)
    assert out.dtype == np.float32
    assert np.allclose(np.linalg.norm(out, axis=1), 1.0, atol=1e-5)


@respx.mock
def test_ollama_prefixes_follow_the_config() -> None:
    route = _ollama_route(dim=3)
    cfg = BGE.model_copy(update={"query_prefix": "query: ", "dim": 3})
    OllamaDenseEncoder(cfg, OLLAMA, options=CATALOGUE_OPTIONS).encode(["Frist"], kind="query")
    assert _body(route)["input"] == ["query: Frist"]


@respx.mock
def test_ollama_9000_token_passage_counts_as_truncated(word_tokenizer: Path) -> None:
    _ollama_route()
    enc = OllamaDenseEncoder(BGE, OLLAMA, count_tokens=load_token_counter(word_tokenizer))
    enc.encode([" ".join(["Arbeitnehmer"] * 9000), "kurz", " ".join(["Frist"] * 900)])
    assert enc.truncated == 1


@respx.mock
def test_ollama_without_tokenizer_falls_back_to_a_lower_bound_count() -> None:
    _ollama_route()
    enc = OllamaDenseEncoder(BGE, OLLAMA)
    enc.encode([" ".join(["Arbeitnehmer"] * 2000)])
    assert enc.truncated == 1


@respx.mock
@pytest.mark.parametrize(
    ("value", "expected"),
    [("k1", "Bearer k1"), ("", None), (None, None)],
)
def test_ollama_bearer_header(
    monkeypatch: pytest.MonkeyPatch, value: str | None, expected: str | None
) -> None:
    if value is None:
        monkeypatch.delenv(ENV, raising=False)
    else:
        monkeypatch.setenv(ENV, value)
    route = _ollama_route()
    OllamaDenseEncoder(BGE, OLLAMA).encode([f"t{i}" for i in range(40)])  # 2 requests
    assert route.call_count == 2
    for call in route.calls:
        assert call.request.headers.get("Authorization") == expected


@respx.mock
def test_api_key_env_null_sends_no_header_even_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV, "k1")
    route = _ollama_route()
    OllamaDenseEncoder(BGE.model_copy(update={"api_key_env": None}), OLLAMA).encode(["x"])
    assert "Authorization" not in route.calls.last.request.headers


@respx.mock
def test_403_error_and_logs_never_contain_the_key(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv(ENV, "k1-secret-value")
    respx.post(f"{OLLAMA}/api/embed").mock(
        return_value=httpx.Response(403, text="bad key k1-secret-value")
    )
    enc = OllamaDenseEncoder(BGE, OLLAMA, sleep=_no_sleep)
    with caplog.at_level(logging.DEBUG), pytest.raises(EncoderError) as err:
        enc.encode(["x"])
    assert "k1-secret-value" not in str(err.value)
    assert "k1-secret-value" not in caplog.text
    assert "403" in str(err.value)


@respx.mock
def test_ollama_503_then_200_is_retried_and_timeout_ends_in_encoder_error() -> None:
    ok = httpx.Response(200, json={"embeddings": [[1.0] + [0.0] * 1023]})
    route = respx.post(f"{OLLAMA}/api/embed").mock(side_effect=[httpx.Response(503), ok])
    out = OllamaDenseEncoder(BGE, OLLAMA, sleep=_no_sleep).encode(["x"])
    assert route.call_count == 2
    assert out.shape == (1, 1024)
    respx.post(f"{OLLAMA}/api/embed").mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(EncoderError, match=r"3 attempts"):
        OllamaDenseEncoder(BGE, OLLAMA, sleep=_no_sleep).encode(["x"])


@respx.mock
@pytest.mark.parametrize(
    "payload",
    [
        {"embeddings": [[1.0, 0.0]]},  # wrong dimension
        {"embeddings": []},  # wrong count
        {"error": "model not found"},  # no embeddings key
        {"embeddings": [[0.0] * 1024]},  # zero vector cannot be normalised
    ],
)
def test_ollama_unusable_answers_are_encoder_errors(payload: dict[str, object]) -> None:
    respx.post(f"{OLLAMA}/api/embed").mock(return_value=httpx.Response(200, json=payload))
    with pytest.raises(EncoderError):
        OllamaDenseEncoder(BGE, OLLAMA, sleep=_no_sleep).encode(["x"])
