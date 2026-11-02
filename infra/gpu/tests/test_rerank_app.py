"""T3.1a CPU tests: ``rerank-cpu`` request/response handling (TEI-compatible ``POST /rerank``, D217, DEV11-03).

The scores come from the real ``BAAI/bge-reranker-v2-m3`` model, recorded once by
``infra/gpu/rerank/record_scores.py`` into ``fixtures/rerank_recorded.json`` (ADR-0008: no invented
scores). The model itself is exercised by the ``[DOCKER]`` check and ``test_endpoints.py`` (gpu).
"""

import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator, Sequence
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from rerank.rerank_app import (
    MAX_TEXTS,
    MAX_TOKENS_FULL,
    MAX_TOKENS_TRUNCATED,
    RerankState,
    handle_rerank,
    make_server,
)

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "rerank_recorded.json").read_text(encoding="utf-8")
)


class RecordedScorer:
    """Replays the scores recorded from the real model; remembers the token limit it was asked for."""

    def __init__(self) -> None:
        self.table = {
            (c["query"], t): s
            for c in FIXTURE["cases"]
            for t, s in zip(c["texts"], c["scores"], strict=True)
        }
        self.max_tokens: int | None = None
        self.calls = 0

    def score(self, query: str, texts: Sequence[str], max_tokens: int) -> list[float]:
        self.calls += 1
        self.max_tokens = max_tokens
        return [self.table[(query, t)] for t in texts]


def _case() -> dict[str, Any]:
    return FIXTURE["cases"][0]  # type: ignore[no-any-return]


def _body(**over: object) -> bytes:
    case = _case()
    return json.dumps(
        {"query": case["query"], "texts": case["texts"], "truncate": True, **over}
    ).encode()


def test_the_response_is_index_and_score_sorted_by_score_descending() -> None:
    scorer = RecordedScorer()
    status, payload = handle_rerank(_body(), scorer)
    assert status == 200
    assert [set(r) for r in payload] == [{"index", "score"}] * len(_case()["texts"])
    scores = [r["score"] for r in payload]
    assert scores == sorted(scores, reverse=True)
    assert sorted(r["index"] for r in payload) == list(range(len(_case()["texts"])))
    assert all(isinstance(r["score"], float) and isinstance(r["index"], int) for r in payload)


def test_the_relevant_german_passage_ranks_above_the_irrelevant_ones() -> None:
    _, payload = handle_rerank(_body(), RecordedScorer())
    assert payload[0]["index"] == _case()["relevant"]
    assert payload[0]["score"] > payload[-1]["score"]


def test_the_scores_are_the_recorded_scores_of_the_real_model() -> None:
    _, payload = handle_rerank(_body(), RecordedScorer())
    by_index = {r["index"]: r["score"] for r in payload}
    assert [by_index[i] for i in range(len(by_index))] == _case()["scores"]


def test_truncate_true_cuts_at_256_tokens_and_false_uses_the_full_limit() -> None:
    scorer = RecordedScorer()
    assert handle_rerank(_body(truncate=True), scorer)[0] == 200
    assert scorer.max_tokens == MAX_TOKENS_TRUNCATED == 256
    assert handle_rerank(_body(truncate=False), scorer)[0] == 200
    assert scorer.max_tokens == MAX_TOKENS_FULL
    assert (
        handle_rerank(
            json.dumps({"query": _case()["query"], "texts": _case()["texts"]}).encode(), scorer
        )[0]
        == 200
    )
    assert scorer.max_tokens == 256  # truncate defaults to true


def test_empty_texts_return_an_empty_list_without_scoring() -> None:
    scorer = RecordedScorer()
    assert handle_rerank(json.dumps({"query": "q", "texts": []}).encode(), scorer) == (200, [])
    assert scorer.calls == 0


@pytest.mark.parametrize(
    ("body", "status"),
    [
        (b"not json", 400), (b"[]", 422), (json.dumps({"texts": ["a"]}).encode(), 422),
        (json.dumps({"query": 3, "texts": ["a"]}).encode(), 422),
        (json.dumps({"query": "q", "texts": "a"}).encode(), 422),
        (json.dumps({"query": "q", "texts": [1]}).encode(), 422),
        (json.dumps({"query": "q", "texts": ["a"] * (MAX_TEXTS + 1)}).encode(), 413),
    ],
)  # fmt: skip
def test_malformed_requests_get_a_4xx_and_are_not_scored(body: bytes, status: int) -> None:
    scorer = RecordedScorer()
    code, payload = handle_rerank(body, scorer)
    assert code == status
    assert "error" in payload
    assert scorer.calls == 0


@pytest.fixture
def server() -> Iterator[tuple[str, RerankState]]:
    state = RerankState(scorer=None)
    httpd: ThreadingHTTPServer = make_server("127.0.0.1", 0, state)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", state
    httpd.shutdown()
    httpd.server_close()


def _get(url: str) -> int:
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:  # noqa: S310
            return int(resp.status)
    except urllib.error.HTTPError as err:
        return err.code


def test_health_is_503_until_the_model_is_loaded_then_200(server: tuple[str, RerankState]) -> None:
    url, state = server
    assert _get(url + "/health") == 503
    state.scorer = RecordedScorer()
    assert _get(url + "/health") == 200


def test_rerank_before_the_model_is_loaded_is_503(server: tuple[str, RerankState]) -> None:
    url, _ = server
    req = urllib.request.Request(url + "/rerank", data=_body(), method="POST")  # noqa: S310
    with pytest.raises(urllib.error.HTTPError) as err:
        urllib.request.urlopen(req, timeout=5)  # noqa: S310
    assert err.value.code == 503


@pytest.mark.parametrize("auth", [None, "Bearer anything", "Basic bm9wZQ=="])
def test_an_authorization_header_is_accepted_and_ignored(
    server: tuple[str, RerankState], auth: str | None
) -> None:
    url, state = server
    state.scorer = RecordedScorer()
    headers = {"Content-Type": "application/json", **({"Authorization": auth} if auth else {})}
    req = urllib.request.Request(url + "/rerank", data=_body(), headers=headers, method="POST")  # noqa: S310
    with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310
        assert resp.status == 200
        payload = json.loads(resp.read())
    assert payload[0]["index"] == _case()["relevant"]


def test_unknown_paths_are_404(server: tuple[str, RerankState]) -> None:
    assert _get(server[0] + "/nope") == 404


def test_there_is_no_auth_logic_in_the_service() -> None:
    source = (Path(__file__).parents[1] / "rerank" / "rerank_app.py").read_text(encoding="utf-8")
    assert "401" not in source
    assert "403" not in source
