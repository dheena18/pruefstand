"""Rerankers: ``CrossEncoderReranker`` (``rerank-cpu``, tier 2) and ``IdentityReranker`` (tier 1).

``rerank-cpu`` is the trusted VM service of T3.1a (TEI wire format ``POST /rerank``, no auth,
D217): the client sends no ``Authorization`` header and reads no key. Tier 2 sends the first
``top_n`` (10) passages, each cut to the catalogue's 256 tokens, in **one** batched request (D222).
"""

import re

import httpx

from rag_demo.errors import RerankError
from rag_demo.models import Hit

_PIECE = re.compile(r"\w+|[^\w\s]")


def truncate_to_tokens(text: str, max_tokens: int) -> str:
    """Cut ``text`` after ``max_tokens`` word and punctuation pieces.

    Words and punctuation marks are a lower bound of the model's tokens, so the cut never removes
    text the model would have kept; the service (``truncate: true``) enforces the exact limit.

    Examples:
        >>> truncate_to_tokens("Die Frist beträgt vier Wochen.", 3)
        'Die Frist beträgt'
        >>> truncate_to_tokens("Kurz.", 256)
        'Kurz.'
    """
    for count, piece in enumerate(_PIECE.finditer(text), start=1):
        if count == max_tokens:
            return text[: piece.end()]
    return text


def renumber(hits: list[Hit]) -> list[Hit]:
    """Return ``hits`` with ranks 1..n."""
    return [h.model_copy(update={"rank": i}) for i, h in enumerate(hits, start=1)]


class IdentityReranker:
    """Keeps the order (tier 1 has no reranker)."""

    def rerank(self, query: str, hits: list[Hit], top_n: int) -> list[Hit]:  # noqa: ARG002
        """Return ``hits`` unchanged (ranks 1..n)."""
        return renumber(hits)


class CrossEncoderReranker:
    """Rerank with ``bge-reranker-v2-m3`` behind ``POST <url>/rerank`` (``rerank-cpu``).

    Args:
        url: Base URL of ``rerank-cpu`` (env ``RERANK_URL``).
        max_passage_tokens: Passages are cut to this many tokens before sending (catalogue).
        timeout_s: Request timeout sized for the CPU (catalogue ``request_timeout_s``).
        client: Optional ``httpx.Client`` (tests).
    """

    def __init__(
        self,
        url: str,
        *,
        max_passage_tokens: int,
        timeout_s: float,
        client: httpx.Client | None = None,
    ) -> None:
        self._url = f"{url.rstrip('/')}/rerank"
        self.max_passage_tokens = max_passage_tokens
        self.timeout_s = timeout_s
        self._client = client or httpx.Client(timeout=timeout_s)

    def rerank(self, query: str, hits: list[Hit], top_n: int) -> list[Hit]:
        """Score the first ``top_n`` hits against ``query``; the rest follows unchanged.

        Args:
            query: The question.
            hits: Fused hits in rank order.
            top_n: How many of them are scored (one batched request).

        Returns:
            The scored hits sorted by score (ties keep the fused order), then the unscored
            remainder; ranks 1..n. ``score`` of the scored hits is the reranker score.

        Raises:
            RerankError: The service is unreachable, answers with an error or a wrong shape.
        """
        head, tail = hits[:top_n], hits[top_n:]
        if not head:
            return renumber(hits)
        scores = self._scores(
            query, [truncate_to_tokens(h.text, self.max_passage_tokens) for h in head]
        )
        order = sorted(range(len(head)), key=lambda i: (-scores[i], i))
        scored = [head[i].model_copy(update={"score": scores[i]}) for i in order]
        return renumber(scored + tail)

    def _scores(self, query: str, texts: list[str]) -> list[float]:
        body = {"query": query, "texts": texts, "truncate": True}
        try:
            resp = self._client.post(self._url, json=body)
        except httpx.HTTPError as err:
            msg = f"rerank-cpu unreachable ({type(err).__name__})"
            raise RerankError(msg) from None
        if resp.status_code != httpx.codes.OK:
            msg = f"rerank-cpu returned HTTP {resp.status_code}"
            raise RerankError(msg)
        try:
            rows = resp.json()
            scores: dict[int, float] = {int(r["index"]): float(r["score"]) for r in rows}
        except (KeyError, TypeError, ValueError):
            msg = "rerank-cpu answered with an unexpected body"
            raise RerankError(msg) from None
        if sorted(scores) != list(range(len(texts))) or len(rows) != len(texts):
            msg = "rerank-cpu answered with a wrong number of scores"
            raise RerankError(msg)
        return [scores[i] for i in range(len(texts))]
