"""Testcontainers fixtures: real Qdrant (slice snapshot or fresh index) and real TEI."""

import json
import time
from collections.abc import Iterator

import httpx
import pytest
import yaml
from rd_support import CONFIGS, MODEL_DIR, REPO, SLICE
from testcontainers.core.container import DockerContainer
from testcontainers.core.waiting_utils import wait_for_logs

from rag_demo.analysis.analyzer import GermanAnalyzer
from rag_demo.analysis.sparse import SparseEncoder
from rag_demo.config import load_config
from rag_demo.dense import TeiDenseEncoder
from rag_demo.index import Indexer
from rag_demo.models import RagConfig
from rag_demo.retrieve import Retriever

COLLECTION = "slice_v2"
SNAPSHOT = REPO / ".cache" / "pruefstand" / "qdrant" / "slice_v2.snapshot"


def _compose_image(service: str) -> str:
    data = yaml.safe_load((REPO / "docker-compose.yml").read_text(encoding="utf-8"))
    return str(data["services"][service]["image"])


def _wait_http(url: str, timeout_s: float = 240.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            if httpx.get(url, timeout=3).is_success:
                return
        except httpx.HTTPError:
            pass
        time.sleep(1)
    msg = f"{url} did not become ready"
    raise TimeoutError(msg)


@pytest.fixture(scope="session")
def tei_url() -> Iterator[str]:
    """The pinned TEI CPU image serving the pinned embedding model (cache under MODEL_DIR/tei)."""
    pins = yaml.safe_load((REPO / "infra" / "models" / "live-models.yaml").read_text("utf-8"))
    emb = pins["embeddings"][0]
    cache = MODEL_DIR / "tei"
    cache.mkdir(parents=True, exist_ok=True)
    container = (
        DockerContainer(_compose_image("embed"))
        .with_command(f"--model-id {emb['repo']} --revision {emb['revision']} --port 80")
        .with_volume_mapping(str(cache), "/data", "rw")
        .with_env("HF_HUB_ENABLE_HF_TRANSFER", "0")
        .with_exposed_ports(80)
    )
    with container:
        wait_for_logs(container, "Ready", timeout=300)
        url = f"http://127.0.0.1:{container.get_exposed_port(80)}"
        _wait_http(f"{url}/health")
        yield url


@pytest.fixture(scope="session")
def qdrant_url(tei_url: str) -> Iterator[str]:
    """Pinned Qdrant with the slice index: snapshot if present, else built with the real TEI."""
    container = DockerContainer(_compose_image("qdrant")).with_exposed_ports(6333)
    with container:
        url = f"http://127.0.0.1:{container.get_exposed_port(6333)}"
        _wait_http(f"{url}/readyz")
        if SNAPSHOT.is_file() and _restore(url):
            yield url
            return
        cfg = load_config(CONFIGS / "rag.yaml")
        Indexer(
            url, _dense(cfg, tei_url), _analyzer(cfg), SparseEncoder(), collection=COLLECTION
        ).index(SLICE)
        yield url


def _restore(url: str) -> bool:
    with SNAPSHOT.open("rb") as handle:
        resp = httpx.post(
            f"{url}/collections/{COLLECTION}/snapshots/upload",
            params={"priority": "snapshot", "wait": "true"},
            files={"snapshot": (SNAPSHOT.name, handle)},
            timeout=120,
        )
    return resp.is_success


def _analyzer(cfg: RagConfig) -> GermanAnalyzer:
    a = cfg.analyzer
    return GermanAnalyzer(a.compound_split, a.stemmer, a.fold_umlauts)


def _dense(cfg: RagConfig, tei_url: str) -> TeiDenseEncoder:
    return TeiDenseEncoder(cfg.embed, tei_url)


class RecordingTransport(httpx.HTTPTransport):
    """Real transport that remembers every request body sent to Qdrant."""

    def __init__(self) -> None:
        super().__init__()
        self.bodies: list[dict[str, object]] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/points/query"):
            self.bodies.append(json.loads(request.content))
        return super().handle_request(request)


@pytest.fixture
def make_retriever(qdrant_url: str, tei_url: str):  # type: ignore[no-untyped-def]  # factory fixture
    def make(config_name: str = "rag.yaml") -> tuple[Retriever, RecordingTransport]:
        cfg = load_config(CONFIGS / config_name)
        transport = RecordingTransport()
        retriever = Retriever(
            cfg,
            qdrant_url,
            _dense(cfg, tei_url),
            _analyzer(cfg),
            SparseEncoder(),
            collection=COLLECTION,
            client=httpx.Client(transport=transport, timeout=30),
        )
        return retriever, transport

    return make


@pytest.fixture(scope="session")
def leak_probes() -> list[str]:
    """20 leak-probe questions: they name facts of the other tenants (planted canaries)."""
    text = (REPO / "apps" / "rag-demo" / "tests" / "live" / "smoke_questions.yaml").read_text(
        "utf-8"
    )
    probes = yaml.safe_load(text)["leak_probes"]
    assert len(probes) == 20
    assert all(isinstance(p, str) for p in probes)
    return [str(p) for p in probes]
