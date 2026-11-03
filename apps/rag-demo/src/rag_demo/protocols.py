"""Structural interfaces between the app's parts (interfaces.md §16)."""

from collections.abc import Sequence
from typing import Literal, Protocol

import numpy as np
from numpy.typing import NDArray

from rag_demo.models import GenOutput, Hit


class DenseEncoder(Protocol):
    """Embeds texts into dense vectors; ``kind`` selects the model's query or passage prefix."""

    truncated: int

    def encode(
        self, texts: Sequence[str], kind: Literal["query", "passage"] = "query"
    ) -> NDArray[np.float32]:
        """Return one row per text."""
        ...


class Generator(Protocol):
    """Writes the answer from the retrieved chunks."""

    async def answer(self, question: str, hits: list[Hit]) -> GenOutput:
        """Return the answer and the chunk ids that entered the prompt."""
        ...


class Reranker(Protocol):
    """Reorders the first ``top_n`` hits by relevance to the query (interfaces §16)."""

    def rerank(self, query: str, hits: list[Hit], top_n: int) -> list[Hit]:
        """Return the first ``top_n`` hits re-scored and reordered, then the rest unchanged.

        Ranks of the result are 1..n without gaps.
        """
        ...
