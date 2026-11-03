"""``CrossEncoderReranker`` against the real ``rerank-cpu`` service (Testcontainers, VM CPU).

The image is built from ``infra/gpu/rerank`` (the service of T3.1a); the pinned weights come from
``$LIVE_MODEL_DIR/rerank`` (a Hugging Face cache; empty = downloaded on the first start, which
needs egress). Same assertion as the recorded cassette of ``tests/unit/retrieval/test_rerank.py``.
"""

import contextlib
import subprocess
from collections.abc import Iterator

import pytest
from rd_support import MODEL_DIR, REPO, RERANK_QUERY, rerank_input, wait_http
from testcontainers.core.container import DockerContainer

from rag_demo.retrieval.rerank import CrossEncoderReranker

pytestmark = pytest.mark.integration
IMAGE = "pruefstand-rerank-cpu:t35-test"


@pytest.fixture(scope="module")
def rerank_url() -> Iterator[str]:
    """The real ``rerank-cpu`` (BAAI/bge-reranker-v2-m3 on the CPU), no auth."""
    subprocess.run(  # noqa: S603  (fixed argument list, no shell)
        ["docker", "build", "-q", "-t", IMAGE, str(REPO / "infra" / "gpu" / "rerank")],  # noqa: S607
        check=True,
        timeout=1800,
    )
    cache = MODEL_DIR / "rerank"
    cache.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(PermissionError):  # already prepared by another user
        cache.chmod(0o777)  # the container user must be able to write the cache
    container = (
        DockerContainer(IMAGE)
        .with_volume_mapping(str(cache), "/models", "rw")
        .with_exposed_ports(8201)
    )
    with container:
        url = f"http://127.0.0.1:{container.get_exposed_port(8201)}"
        wait_http(f"{url}/health", timeout_s=900)
        yield url


def test_the_real_service_moves_paragraph_622_to_rank_one(rerank_url: str) -> None:
    reranker = CrossEncoderReranker(rerank_url, max_passage_tokens=256, timeout_s=120.0)
    before = rerank_input()
    after = reranker.rerank(RERANK_QUERY, before, top_n=10)
    assert after[0].chunk_id == "gii-bgb-622#1"
    assert [h.rank for h in after] == list(range(1, 11))
    assert after[0].score > after[-1].score
