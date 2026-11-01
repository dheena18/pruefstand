"""``TeiDenseEncoder``: dense embeddings from a Text Embeddings Inference server (CPU)."""

import logging
import re
from collections.abc import Sequence
from typing import Any, Literal

import httpx
import numpy as np
from numpy.typing import NDArray

from rag_demo.auth import auth_headers
from rag_demo.errors import EmbeddingError
from rag_demo.models import EmbedCfg

_log = logging.getLogger(__name__)
_TOKEN = re.compile(r"\w+|[^\w\s]")
BATCH = 16


def build_embed_request(
    texts: Sequence[str], cfg: EmbedCfg, kind: Literal["query", "passage"]
) -> dict[str, Any]:
    """Build the TEI ``/embed`` body: prefixed inputs and ``truncate: true`` (W3.10).

    Examples:
        >>> cfg = EmbedCfg(model="e5", query_prefix="query: ")
        >>> build_embed_request(["Frist"], cfg, "query")["inputs"]
        ['query: Frist']
    """
    prefix = cfg.query_prefix if kind == "query" else cfg.doc_prefix
    return {"inputs": [prefix + text for text in texts], "truncate": True, "normalize": True}


def count_truncated(texts: Sequence[str], limit: int) -> int:
    """Count texts that certainly exceed ``limit`` tokens (the word count is a lower bound)."""
    return sum(1 for text in texts if len(_TOKEN.findall(text)) > limit)


class TeiDenseEncoder:
    """Embed texts through TEI. Not thread-safe for the ``truncated`` counter (diagnostic only).

    Args:
        cfg: Model entry (prefixes, input limit, vector size, key variable name).
        base_url: TEI base URL, e.g. ``http://localhost:8090``.
        client: Optional ``httpx.Client`` (tests); default one with ``timeout_s``.
        timeout_s: Request timeout.

    Attributes:
        truncated: Passages longer than the model limit seen so far (they are cut by TEI).
    """

    def __init__(
        self,
        cfg: EmbedCfg,
        base_url: str,
        *,
        client: httpx.Client | None = None,
        timeout_s: float = 180.0,
    ) -> None:
        self._cfg = cfg
        self._url = f"{base_url.rstrip('/')}/embed"
        self._headers = auth_headers(cfg.api_key_env)  # read once, never logged
        self._client = client or httpx.Client(timeout=timeout_s)
        self.truncated = 0

    def encode(
        self, texts: Sequence[str], kind: Literal["query", "passage"] = "query"
    ) -> NDArray[np.float32]:
        """Embed ``texts`` in batches of 16.

        Args:
            texts: Raw texts (prefixes are added here).
            kind: ``"query"`` or ``"passage"``.

        Returns:
            Array of shape ``(len(texts), dim)``.

        Raises:
            EmbeddingError: HTTP error, unreachable server or wrong shape.
        """
        cut = count_truncated(texts, self._cfg.max_input_tokens)
        if cut:
            self.truncated += cut
            _log.info("embedding_truncated passages=%d limit=%d", cut, self._cfg.max_input_tokens)
        rows: list[list[float]] = []
        for start in range(0, len(texts), BATCH):
            rows.extend(
                self._post(build_embed_request(texts[start : start + BATCH], self._cfg, kind))
            )
        out = np.asarray(rows, dtype=np.float32)
        if out.shape != (len(texts), self._cfg.dim):
            msg = f"embedding shape {out.shape}, expected {(len(texts), self._cfg.dim)}"
            raise EmbeddingError(msg)
        return out

    def _post(self, body: dict[str, Any]) -> list[list[float]]:
        try:
            resp = self._client.post(self._url, json=body, headers=self._headers)
        except httpx.HTTPError as err:
            msg = f"embedding service unreachable ({type(err).__name__})"
            raise EmbeddingError(msg) from None
        if resp.status_code != 200:
            msg = f"embedding service returned HTTP {resp.status_code}"
            raise EmbeddingError(msg)
        data: list[list[float]] = resp.json()
        return data
