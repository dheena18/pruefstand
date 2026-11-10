from collections.abc import Iterator
from pathlib import Path

from pruefstand.core.enums import Category
from pruefstand.core.models.baseline import PromotionOverride
from pruefstand.core.models.corpus import Chunk, Document
from pruefstand.core.models.metric import MetricKind, MetricValue
from pruefstand.core.models.run import RunArtifacts
from pruefstand.core.models.target import (
    RetrieveResponse,
    TargetInfo,
    TargetRequest,
    TargetResponse,
)
from pruefstand.core.models.testcase import TestCase
from pruefstand.core.protocols import (
    BaselineStore,
    Chunker,
    DeterministicMetric,
    KVCache,
    Loader,
    Metric,
    TargetAdapter,
)


class DictCache:
    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}

    def get(self, key: str) -> bytes | None:
        return self.data.get(key)

    def set(self, key: str, value: bytes) -> None:
        self.data[key] = value


class DummyAdapter:
    async def info(self) -> TargetInfo | None:
        return None

    async def query(self, req: TargetRequest) -> TargetResponse:
        return TargetResponse(answer=req.question)

    async def retrieve(self, req: TargetRequest) -> RetrieveResponse | None:
        return None

    async def aclose(self) -> None:
        return None


class DummyStore:
    def get(self, eval_fingerprint: str, ref: str = "main") -> RunArtifacts | None:
        return None

    def put(
        self, run: RunArtifacts, ref: str = "main", *, override: PromotionOverride | None = None
    ) -> None:
        return None


class DummyLoader:
    def load(self, raw_dir: Path) -> Iterator[Document]:
        return iter(())


class DummyChunker:
    def chunk(self, doc: Document) -> list[Chunk]:
        return []


class DummyMetric:
    name = "dummy"
    version = "1"
    kind = MetricKind.DETERMINISTIC
    higher_is_better = True
    requires: frozenset[str] = frozenset()
    applies_to: frozenset[Category] | None = None

    def compute(self, case: TestCase, resp: TargetResponse) -> MetricValue:
        raise NotImplementedError


def test_dummies_satisfy_protocols() -> None:
    assert isinstance(DictCache(), KVCache)
    assert isinstance(DummyAdapter(), TargetAdapter)
    assert isinstance(DummyStore(), BaselineStore)
    assert isinstance(DummyLoader(), Loader)
    assert isinstance(DummyChunker(), Chunker)
    assert isinstance(DummyMetric(), Metric)
    assert isinstance(DummyMetric(), DeterministicMetric)


def test_incomplete_classes_do_not_satisfy_protocols() -> None:
    assert not isinstance(object(), KVCache)
    assert not isinstance(DictCache(), TargetAdapter)
    assert not isinstance(DummyChunker(), Metric)
