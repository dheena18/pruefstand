"""TeiDenseEncoder and OllamaDenseEncoder against their real HTTP APIs (respx plumbing).

Request shapes, batching, retries, the bearer header (D216) and the truncation counter are tested
here; the vectors of the real models are covered by the recorded TEI cassette, the `live` and the
`gpu` tests.
"""

import json
from pathlib import Path

import httpx
import numpy as np
import pytest
import respx
from rd_support import CONFIGS, write_word_tokenizer

from rag_demo.config import load_config
from rag_demo.errors import ConfigError, EmbeddingError, EncoderError
from rag_demo.index.encoders import TeiDenseEncoder
from rag_demo.index.tokens import approx_token_count, load_token_counter
from rag_demo.models import EmbedCfg

ENV = "PRUEFSTAND_CANDIDATE_API_KEY"
TEI = "http://embed.test:8090"
E5 = EmbedCfg(
    model="intfloat/multilingual-e5-small",
    query_prefix="query: ",
    doc_prefix="passage: ",
    max_input_tokens=512,
    dim=3,
)
RAW = EmbedCfg(model="plain", dim=3)


def _no_sleep(_seconds: float) -> None:
    return None


def _tei_route() -> respx.Route:
    return respx.post(f"{TEI}/embed").mock(
        side_effect=lambda req: httpx.Response(
            200, json=[[0.1, 0.2, 0.3]] * len(json.loads(req.content)["inputs"])
        )
    )


def _body(route: respx.Route) -> dict[str, object]:
    return json.loads(route.calls.last.request.content)  # type: ignore[no-any-return]  # json


@pytest.fixture(scope="module")
def word_tokenizer(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A real `tokenizers` word-level tokenizer file (one token per word)."""
    return write_word_tokenizer(tmp_path_factory.mktemp("tok") / "tokenizer.json")


# --- TEI (tier 1) ---------------------------------------------------------------------------


@respx.mock
def test_e5_queries_carry_the_query_prefix_and_truncate() -> None:
    route = _tei_route()
    TeiDenseEncoder(E5, TEI).encode(["Kündigungsfrist"], kind="query")
    assert _body(route)["inputs"] == ["query: Kündigungsfrist"]
    assert _body(route)["truncate"] is True


@respx.mock
def test_e5_passages_carry_the_passage_prefix() -> None:
    route = _tei_route()
    TeiDenseEncoder(E5, TEI).encode(["§ 622 BGB", "Art. 6 DSGVO"], kind="passage")
    assert _body(route)["inputs"] == ["passage: § 622 BGB", "passage: Art. 6 DSGVO"]
    assert _body(route)["truncate"] is True


@respx.mock
def test_model_without_prefixes_sends_raw_text() -> None:
    route = _tei_route()
    TeiDenseEncoder(RAW, TEI).encode(["Gebühren"], kind="passage")
    assert _body(route)["inputs"] == ["Gebühren"]
    assert _body(route)["truncate"] is True


@respx.mock
def test_a_3000_token_passage_indexes_and_counts_as_truncated() -> None:
    route = _tei_route()
    enc = TeiDenseEncoder(E5, TEI)
    out = enc.encode([" ".join(["Arbeitnehmer"] * 3000), "kurz"], kind="passage")
    assert route.call_count == 1
    assert enc.truncated == 1
    assert out.shape == (2, 3)
    assert out.dtype == np.float32


@respx.mock
def test_tei_batches_70_texts_into_3_requests() -> None:
    route = _tei_route()
    out = TeiDenseEncoder(RAW, TEI).encode([f"t{i}" for i in range(70)], kind="passage")
    assert route.call_count == 3
    assert [len(json.loads(c.request.content)["inputs"]) for c in route.calls] == [32, 32, 6]
    assert out.shape == (70, 3)


@respx.mock
def test_tei_503_then_200_is_retried() -> None:
    route = respx.post(f"{TEI}/embed").mock(
        side_effect=[httpx.Response(503), httpx.Response(200, json=[[0.1, 0.2, 0.3]])]
    )
    out = TeiDenseEncoder(RAW, TEI, sleep=_no_sleep).encode(["x"], kind="passage")
    assert route.call_count == 2
    assert out.shape == (1, 3)


@respx.mock
def test_tei_timeout_is_retried_then_raises_encoder_error() -> None:
    route = respx.post(f"{TEI}/embed").mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(EncoderError, match=r"unreachable.*3 attempts"):
        TeiDenseEncoder(RAW, TEI, timeout_s=0.5, sleep=_no_sleep).encode(["x"])
    assert route.call_count == 3


@respx.mock
def test_tei_client_error_is_not_retried() -> None:
    route = respx.post(f"{TEI}/embed").mock(return_value=httpx.Response(413))
    with pytest.raises(EncoderError, match="HTTP 413"):
        TeiDenseEncoder(RAW, TEI, sleep=_no_sleep).encode(["x"])
    assert route.call_count == 1


@respx.mock
def test_tei_wrong_shape_is_an_encoder_error() -> None:
    respx.post(f"{TEI}/embed").mock(return_value=httpx.Response(200, json=[[0.1, 0.2]]))
    with pytest.raises(EncoderError, match="shape"):
        TeiDenseEncoder(RAW, TEI, sleep=_no_sleep).encode(["x"])


def test_encoder_error_is_an_embedding_error() -> None:
    assert issubclass(EncoderError, EmbeddingError)  # the API maps it to 503 like before


@pytest.mark.default_cassette("tei_query_e5.yaml")
@pytest.mark.vcr
def test_recorded_real_tei_answer_has_the_configured_shape() -> None:
    cfg = load_config(CONFIGS / "rag.yaml")
    vectors = TeiDenseEncoder(cfg.embed, "http://embed.test:8090").encode(
        ["Welche Kündigungsfrist gilt nach zwei Jahren Betriebszugehörigkeit?"], kind="query"
    )
    assert vectors.shape == (1, cfg.embed.dim)
    assert abs(float(np.linalg.norm(vectors[0])) - 1.0) < 1e-3  # TEI normalises


# --- helpers --------------------------------------------------------------------------------


@respx.mock
def test_tei_embedding_request_carries_the_bearer_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV, "k1")
    route = _tei_route()
    TeiDenseEncoder(RAW, TEI).encode(["x"])
    assert route.calls.last.request.headers["Authorization"] == "Bearer k1"


@respx.mock
@pytest.mark.parametrize("value", [None, ""])
def test_tei_no_header_when_unset_or_empty(
    monkeypatch: pytest.MonkeyPatch, value: str | None
) -> None:
    if value is None:
        monkeypatch.delenv(ENV, raising=False)
    else:
        monkeypatch.setenv(ENV, value)
    route = _tei_route()
    TeiDenseEncoder(RAW, TEI).encode(["x"])
    assert "Authorization" not in route.calls.last.request.headers


def test_approx_count_is_a_lower_bound_of_words_and_punctuation() -> None:
    assert approx_token_count("Frist (§ 622)") == 5


def test_token_counter_uses_the_model_tokenizer(word_tokenizer: Path) -> None:
    count = load_token_counter(word_tokenizer)
    assert count("a b c") == 3
    assert count("") == 0


def test_missing_tokenizer_file_is_a_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="tokenizer"):
        load_token_counter(tmp_path / "nope.json")
