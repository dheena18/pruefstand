"""TeiDenseEncoder against the TEI HTTP API (respx): prefixes, truncate flag, counter."""

import json

import httpx
import respx
from rag_demo.dense import TeiDenseEncoder
from rag_demo.models import EmbedCfg

BASE = "http://embed.test:8090"
E5 = EmbedCfg(
    model="intfloat/multilingual-e5-small",
    query_prefix="query: ",
    doc_prefix="passage: ",
    max_input_tokens=512,
    dim=3,
)
RAW = EmbedCfg(model="plain", dim=3)


def _route() -> respx.Route:
    return respx.post(f"{BASE}/embed").mock(
        side_effect=lambda req: httpx.Response(
            200, json=[[0.1, 0.2, 0.3]] * len(json.loads(req.content)["inputs"])
        )
    )


def _body(route: respx.Route) -> dict[str, object]:
    return json.loads(route.calls.last.request.content)  # type: ignore[no-any-return]  # json


@respx.mock
def test_e5_queries_carry_the_query_prefix_and_truncate() -> None:
    route = _route()
    TeiDenseEncoder(E5, BASE).encode(["Kündigungsfrist"], kind="query")
    body = _body(route)
    assert body["inputs"] == ["query: Kündigungsfrist"]
    assert body["truncate"] is True


@respx.mock
def test_e5_passages_carry_the_passage_prefix() -> None:
    route = _route()
    TeiDenseEncoder(E5, BASE).encode(["§ 622 BGB", "Art. 6 DSGVO"], kind="passage")
    body = _body(route)
    assert body["inputs"] == ["passage: § 622 BGB", "passage: Art. 6 DSGVO"]
    assert body["truncate"] is True


@respx.mock
def test_model_without_prefixes_sends_raw_text() -> None:
    route = _route()
    TeiDenseEncoder(RAW, BASE).encode(["Gebühren"], kind="passage")
    assert _body(route)["inputs"] == ["Gebühren"]
    assert _body(route)["truncate"] is True


@respx.mock
def test_long_passage_is_sent_once_and_counted_as_truncated() -> None:
    route = _route()
    enc = TeiDenseEncoder(E5, BASE)
    long_text = " ".join(["Arbeitnehmer"] * 3000)
    out = enc.encode([long_text, "kurz"], kind="passage")
    assert route.call_count == 1
    assert enc.truncated == 1
    assert out.shape == (2, 3)
    assert out.dtype.name == "float32"
