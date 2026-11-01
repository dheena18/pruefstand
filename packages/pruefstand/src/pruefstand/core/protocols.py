"""Structural protocols implemented by other modules (interfaces §4, §5, §7, §11).

``LLMBackend`` / ``LLMClientLike`` (T1.4), ``JudgePoolLike`` / ``JudgedMetric`` (T1.8) and
``Perturbation`` / ``LLMPerturbation`` (T4.4, T4.5) are added by their owning tasks.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Protocol, runtime_checkable

from pruefstand.core.enums import Category
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


@runtime_checkable
class KVCache(Protocol):
    """Byte key-value cache (``DiskKVCache``, ``LayeredKVCache``)."""

    def get(self, key: str) -> bytes | None:
        """Return the stored value or None."""
        ...

    def set(self, key: str, value: bytes) -> None:
        """Store ``value`` under ``key``."""
        ...


@runtime_checkable
class TargetAdapter(Protocol):
    """Client of a system under test."""

    async def info(self) -> TargetInfo | None:
        """Return ``/v1/info`` or None for an opaque target."""
        ...

    async def query(self, req: TargetRequest) -> TargetResponse:
        """Answer one question. Raises ``TargetError``."""
        ...

    async def retrieve(self, req: TargetRequest) -> RetrieveResponse | None:
        """Retrieve only (R11 D218); None when the target has no such endpoint (404/405)."""
        ...

    async def aclose(self) -> None:
        """Release connections."""
        ...


@runtime_checkable
class BaselineStore(Protocol):
    """Baseline runs keyed by ``eval_fingerprint`` and ref."""

    def get(self, eval_fingerprint: str, ref: str = "main") -> RunArtifacts | None:
        """Return the baseline for the fingerprint and ref, or None."""
        ...

    def put(self, run: RunArtifacts, ref: str = "main") -> None:
        """Store ``run`` as the baseline for its fingerprint and ref."""
        ...


@runtime_checkable
class Loader(Protocol):
    """Reads raw source files into documents."""

    def load(self, raw_dir: Path) -> Iterator[Document]:
        """Yield the documents found under ``raw_dir``."""
        ...


@runtime_checkable
class Chunker(Protocol):
    """Splits a document into chunks."""

    def chunk(self, doc: Document) -> list[Chunk]:
        """Return the chunks of ``doc``."""
        ...


@runtime_checkable
class Metric(Protocol):
    """A named, versioned metric."""

    name: str
    version: str
    kind: MetricKind
    higher_is_better: bool
    requires: frozenset[str]
    applies_to: frozenset[Category] | None


@runtime_checkable
class DeterministicMetric(Metric, Protocol):
    """A metric computed without an LLM."""

    def compute(self, case: TestCase, resp: TargetResponse) -> MetricValue:
        """Compute the metric for one case."""
        ...
