"""Factory type aliases for the metric tests (fixtures live in unit/metrics/conftest.py)."""

from collections.abc import Callable

from pruefstand.core.models.target import RetrievedChunk, TargetResponse
from pruefstand.core.models.testcase import TestCase

CaseFactory = Callable[..., TestCase]
RespFactory = Callable[..., TargetResponse]
ChunkFactory = Callable[..., RetrievedChunk]
