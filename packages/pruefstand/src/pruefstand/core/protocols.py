"""Structural protocols implemented by other modules (interfaces §4, §5, §7, §11).

``Perturbation`` is added by T4.4, ``LLMPerturbation`` by T4.5.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Protocol, TypeVar, runtime_checkable

import numpy as np
from pydantic import BaseModel

from pruefstand.core.enums import Category
from pruefstand.core.models.baseline import PromotionOverride
from pruefstand.core.models.corpus import Chunk, Document
from pruefstand.core.models.judge import JudgeTask, JudgeVerdict
from pruefstand.core.models.llm import LLMRequest, LLMResponse
from pruefstand.core.models.metric import MetricKind, MetricValue
from pruefstand.core.models.perturb import PerturbResult
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


T = TypeVar("T", bound=BaseModel)


@runtime_checkable
class LLMBackend(Protocol):
    """One real model endpoint behind ``LLMClient`` (``LiteLLMBackend``, cassette replay)."""

    async def acomplete(self, req: LLMRequest) -> LLMResponse:
        """Call the model once. Raises ``LLMError`` (``transient``: a retry may work)."""
        ...


@runtime_checkable
class LLMClientLike(Protocol):
    """The part of ``LLMClient`` that metrics and perturbations need."""

    async def complete(self, req: LLMRequest) -> LLMResponse:
        """Return the (possibly cached) answer. Raises ``LLMError``, ``BudgetExceeded``."""
        ...

    async def complete_json(self, req: LLMRequest, schema: type[T]) -> T:
        """Return the answer parsed into ``schema``. Raises ``LLMError``."""
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

    def put(
        self, run: RunArtifacts, ref: str = "main", *, override: PromotionOverride | None = None
    ) -> None:
        """Store ``run`` as the baseline for its fingerprint and ref (``override``: D1123)."""
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


@runtime_checkable
class JudgeLike(Protocol):
    """One judge model (``judges.Judge``, T5.2a)."""

    @property
    def input_cap(self) -> int:
        """Largest rendered prompt in tokens (context window minus 1 024, round 9 X3.9)."""
        ...

    def prompt_tokens(self, task: JudgeTask) -> int:
        """Estimate the tokens of the prompt ``score`` would send for ``task`` (no call)."""
        ...

    async def score(self, task: JudgeTask) -> JudgeVerdict:
        """Judge one task. Raises ``LLMError``, ``PolicyViolation``, ``QuotaExhausted``."""
        ...


@runtime_checkable
class JudgePoolLike(Protocol):
    """The judges of a run, by metric (``judges.JudgePool``, T5.2a)."""

    def for_metric(self, metric: str) -> JudgeLike:
        """Return the judge that scores ``metric``."""
        ...


@runtime_checkable
class JudgedMetric(Metric, Protocol):
    """A metric computed with an LLM judge."""

    async def acompute(
        self, case: TestCase, resp: TargetResponse, judges: JudgePoolLike
    ) -> MetricValue:
        """Compute the metric for one case. Raises ``LLMError``, ``BudgetExceeded``."""
        ...


@runtime_checkable
class Perturbation(Protocol):
    """A rule-based, deterministic question perturbation (``pruefstand.perturb``)."""

    name: str
    version: str
    uses_llm: bool

    def apply(self, text: str, rng: np.random.Generator) -> PerturbResult:
        """Perturb ``text``; ``changed`` is False when no rule applied. Never raises on text."""
        ...


@runtime_checkable
class LLMPerturbation(Perturbation, Protocol):
    """A perturbation that may call a model (compound_split, register, gender, colloquial)."""

    async def aapply(
        self, text: str, llm: LLMClientLike, rng: np.random.Generator
    ) -> PerturbResult:
        """Rewrite ``text`` and validate the rewrite.

        Returns:
            The accepted rewrite, or the unchanged text with ``changed=False`` and the reason in
            ``notes``.

        Raises:
            LLMError: The model call failed (``PolicyViolation``, ``QuotaExhausted``, ...).
        """
        ...
