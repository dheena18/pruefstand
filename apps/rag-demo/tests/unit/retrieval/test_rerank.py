"""Rerankers: the recorded answer of the real ``rerank-cpu`` and the request rules of D217/D222."""

import json
import re

import httpx
import pytest
import respx
from rd_support import (
    CONFIGS,
    RERANK_QUERY,
    fixture_hit,
    fixture_rows,
    rerank_input,
)

from rag_demo.catalogue import load_catalogue
from rag_demo.config import load_config
from rag_demo.errors import ConfigError, RerankError
from rag_demo.retrieval.rerank import (
    CrossEncoderReranker,
    IdentityReranker,
    renumber,
    truncate_to_tokens,
)
from rag_demo.wiring import build_reranker

URL = "http://rerank-cpu.test:8201"
CATALOGUE = CONFIGS.parents[2] / "infra" / "gpu" / "models.yaml"
PIECE = re.compile(r"\w+|[^\w\s]")


def _reranker() -> CrossEncoderReranker:
    return CrossEncoderReranker(URL, max_passage_tokens=256, timeout_s=5.0)


@pytest.mark.default_cassette("rerank_622.yaml")
@pytest.mark.vcr
def test_the_recorded_real_service_moves_paragraph_622_to_rank_one() -> None:
    before = rerank_input()
    assert before[-1].chunk_id == "gii-bgb-622#1"  # the best chunk starts last
    after = _reranker().rerank(RERANK_QUERY, before, top_n=10)
    assert after[0].chunk_id == "gii-bgb-622#1"
    assert [h.rank for h in after] == list(range(1, 11))
    assert {h.chunk_id for h in after} == {h.chunk_id for h in before}
    assert after[0].score > after[1].score >= after[-1].score
    assert after[0].text == before[-1].text  # the full text, only the request is cut


def test_the_identity_reranker_keeps_the_order_and_the_scores() -> None:
    hits = rerank_input()
    out = IdentityReranker().rerank(RERANK_QUERY, hits, top_n=3)
    assert [h.chunk_id for h in out] == [h.chunk_id for h in hits]
    assert [h.score for h in out] == [0.1] * 10


@respx.mock
def test_exactly_top_n_passages_go_out_in_one_request_the_rest_follows() -> None:
    route = respx.post(f"{URL}/rerank").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"index": 2, "score": 0.9},
                {"index": 0, "score": 0.5},
                {"index": 1, "score": 0.1},
            ],
        )
    )
    hits = rerank_input()
    out = _reranker().rerank(RERANK_QUERY, hits, top_n=3)
    assert route.call_count == 1
    body = json.loads(route.calls.last.request.content)
    assert body["query"] == RERANK_QUERY
    assert body["truncate"] is True
    assert body["texts"] == [h.text for h in hits[:3]]
    assert [h.chunk_id for h in out[:3]] == [hits[2].chunk_id, hits[0].chunk_id, hits[1].chunk_id]
    assert [h.chunk_id for h in out[3:]] == [h.chunk_id for h in hits[3:]]
    assert [h.rank for h in out] == list(range(1, 11))


@respx.mock
def test_passages_longer_than_256_tokens_are_cut_before_sending() -> None:
    long_text = " ".join(str(r["text"]) for r in list(fixture_rows().values())[:8])
    assert len(PIECE.findall(long_text)) > 256
    hit = fixture_hit("gii-bgb-622#1").model_copy(update={"text": long_text})
    route = respx.post(f"{URL}/rerank").mock(
        return_value=httpx.Response(200, json=[{"index": 0, "score": 0.5}])
    )
    out = _reranker().rerank("Frist", [hit], top_n=10)
    (sent,) = json.loads(route.calls.last.request.content)["texts"]
    assert len(PIECE.findall(sent)) == 256
    assert long_text.startswith(sent)
    assert out[0].text == long_text  # the hit keeps its full text


@respx.mock
def test_no_authorization_header_is_sent_even_when_the_candidate_key_is_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRUEFSTAND_CANDIDATE_API_KEY", "must-not-be-sent")
    route = respx.post(f"{URL}/rerank").mock(
        return_value=httpx.Response(200, json=[{"index": 0, "score": 0.5}])
    )
    _reranker().rerank("Frist", [fixture_hit("gii-bgb-622#1")], top_n=10)
    headers = route.calls.last.request.headers
    assert "authorization" not in headers
    assert "must-not-be-sent" not in str(headers)


@respx.mock
def test_equal_scores_keep_the_fused_order() -> None:
    respx.post(f"{URL}/rerank").mock(
        return_value=httpx.Response(200, json=[{"index": i, "score": 0.5} for i in (2, 0, 1)])
    )
    hits = rerank_input()[:3]
    out = _reranker().rerank("Frist", hits, top_n=3)
    assert [h.chunk_id for h in out] == [h.chunk_id for h in hits]


@respx.mock
def test_no_hits_means_no_request() -> None:
    route = respx.post(f"{URL}/rerank")
    assert _reranker().rerank("Frist", [], top_n=10) == []
    assert route.call_count == 0


@respx.mock
@pytest.mark.parametrize(
    "answer",
    [
        httpx.Response(500),
        httpx.Response(200, text="not json"),
        httpx.Response(200, json={"error": "x"}),
        httpx.Response(200, json=[{"index": 0}]),
        httpx.Response(200, json=[{"index": 0, "score": 0.5}]),  # one score for two passages
        httpx.Response(200, json=[{"index": 0, "score": 0.5}, {"index": 0, "score": 0.4}]),
        httpx.Response(200, json=[{"index": 0, "score": 0.5}, {"index": 5, "score": 0.4}]),
    ],
)
def test_a_bad_answer_is_a_rerank_error(answer: httpx.Response) -> None:
    respx.post(f"{URL}/rerank").mock(return_value=answer)
    with pytest.raises(RerankError):
        _reranker().rerank("Frist", rerank_input()[:2], top_n=2)


@respx.mock
def test_an_unreachable_service_is_a_rerank_error_without_details() -> None:
    respx.post(f"{URL}/rerank").mock(side_effect=httpx.ConnectError("secret detail"))
    with pytest.raises(RerankError, match="unreachable") as err:
        _reranker().rerank("Frist", rerank_input()[:2], top_n=2)
    assert "secret detail" not in str(err.value)


def test_truncate_to_tokens_cuts_after_n_pieces() -> None:
    assert truncate_to_tokens("Die Frist beträgt vier Wochen.", 3) == "Die Frist beträgt"
    assert truncate_to_tokens("Die Frist.", 3) == "Die Frist."
    assert truncate_to_tokens("", 3) == ""


def test_renumber_gives_ranks_from_one() -> None:
    assert [h.rank for h in renumber(list(reversed(rerank_input())))] == list(range(1, 11))


# --- wiring: which reranker a config builds ---------------------------------------------------


def test_the_tier_1_config_builds_the_identity_reranker() -> None:
    assert isinstance(build_reranker(load_config(CONFIGS / "rag.yaml")), IdentityReranker)


def test_the_tier_2_config_builds_the_cross_encoder_from_the_catalogue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RERANK_URL", "http://rerank-cpu:8201")
    cfg = load_config(CONFIGS / "rag.gpu.yaml", catalogue_path=CATALOGUE)
    assert cfg.reranker == "on"
    assert cfg.rerank.top_n == 10
    reranker = build_reranker(cfg, load_catalogue(CATALOGUE))
    assert isinstance(reranker, CrossEncoderReranker)
    assert (reranker.max_passage_tokens, reranker.timeout_s) == (256, 60.0)  # the catalogue entry


def test_the_gpu_reranker_off_config_builds_the_identity_reranker() -> None:
    cfg = load_config(CONFIGS / "bugs" / "gpu" / "reranker_off.yaml", catalogue_path=CATALOGUE)
    assert isinstance(build_reranker(cfg, load_catalogue(CATALOGUE)), IdentityReranker)


def test_reranker_on_without_the_url_variable_is_a_config_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("RERANK_URL", raising=False)
    cfg = load_config(CONFIGS / "rag.gpu.yaml", catalogue_path=CATALOGUE)
    with pytest.raises(ConfigError, match="RERANK_URL"):
        build_reranker(cfg, load_catalogue(CATALOGUE))


def test_the_rerank_url_must_be_internal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RERANK_URL", "https://api.example.com")
    cfg = load_config(CONFIGS / "rag.gpu.yaml", catalogue_path=CATALOGUE)
    with pytest.raises(ConfigError, match="not internal"):
        build_reranker(cfg, load_catalogue(CATALOGUE))
