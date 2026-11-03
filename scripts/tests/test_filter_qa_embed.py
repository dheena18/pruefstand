"""The embedding client of ``scripts/filter_qa.py`` (T4.3): batching, endpoints, failures."""

import json

import httpx
import numpy as np
import pytest
from filter_qa_embed import make_embedder

from pruefstand.core.errors import DatasetError


def _transport(handler: httpx.MockTransport) -> httpx.Client:
    return httpx.Client(transport=handler)


def test_the_tei_embedder_batches_and_returns_float32() -> None:
    sizes: list[int] = []

    def handle(request: httpx.Request) -> httpx.Response:
        inputs = json.loads(request.content)["inputs"]
        sizes.append(len(inputs))
        return httpx.Response(200, json=[[1.0, 0.0]] * len(inputs))

    embed = make_embedder(
        "http://e.invalid/", "tei", "m", client=_transport(httpx.MockTransport(handle))
    )
    got = embed([f"t{i}" for i in range(40)])
    assert sizes == [32, 8]
    assert got.shape == (40, 2)
    assert got.dtype == np.float32


def test_the_ollama_embedder_uses_the_native_endpoint() -> None:
    seen: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(200, json={"embeddings": [[0.5, 0.5]]})

    embed = make_embedder(
        "http://e.invalid", "ollama", "bge-m3", client=_transport(httpx.MockTransport(handle))
    )
    assert embed(["a"]).shape == (1, 2)
    assert seen == ["/api/embed"]


def test_embedding_failures_are_dataset_errors() -> None:
    bad_shape = httpx.MockTransport(lambda r: httpx.Response(200, json=[[1.0]]))
    down = httpx.MockTransport(lambda r: httpx.Response(503))
    with pytest.raises(DatasetError, match="unexpected shape"):
        make_embedder("http://e.invalid", "tei", "m", client=_transport(bad_shape))(["a", "b"])
    with pytest.raises(DatasetError, match="failed"):
        make_embedder("http://e.invalid", "tei", "m", client=_transport(down))(["a"])
