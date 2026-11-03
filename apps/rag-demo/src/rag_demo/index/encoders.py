"""Dense encoders: ``TeiDenseEncoder`` (tier 1, TEI CPU) and ``OllamaDenseEncoder`` (tier 2).

Both are real HTTP clients (batch 32, timeout, retries with backoff). Tier 2 uses the native
``POST <url>/api/embed`` only (never ``/v1/embeddings``, D219) with the catalogue ``options`` so
that Ollama does not reload the model (D221); the bearer key (D216) is read once at construction.
"""

import logging
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Literal

import httpx
import numpy as np
from numpy.typing import NDArray

from rag_demo.auth import auth_headers
from rag_demo.errors import ConfigError, EncoderError
from rag_demo.index.tokens import TokenCounter, approx_token_count
from rag_demo.models import EmbedCfg

_log = logging.getLogger(__name__)
BATCH = 32
ATTEMPTS = 3
RETRY_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})
Kind = Literal["query", "passage"]


def build_embed_request(texts: Sequence[str], cfg: EmbedCfg, kind: Kind) -> list[str]:
    """Prefix the texts with the model's query or passage prefix (round-8 W3.10).

    Examples:
        >>> build_embed_request(["Frist"], EmbedCfg(model="e5", query_prefix="query: "), "query")
        ['query: Frist']
    """
    prefix = cfg.query_prefix if kind == "query" else cfg.doc_prefix
    return [prefix + text for text in texts]


class _HttpEncoder:
    """Batching, retrying and truncation counting shared by both encoders."""

    def __init__(
        self,
        cfg: EmbedCfg,
        url: str,
        *,
        client: httpx.Client | None,
        timeout_s: float,
        sleep: Callable[[float], None],
        count_tokens: TokenCounter | None,
    ) -> None:
        self._cfg = cfg
        self._url = url
        self._headers = auth_headers(cfg.api_key_env)  # read once, never logged
        self._client = client or httpx.Client(timeout=timeout_s)
        self._sleep = sleep
        self._count = count_tokens or approx_token_count
        self.truncated = 0

    def encode(self, texts: Sequence[str], kind: Kind = "query") -> NDArray[np.float32]:
        """Embed ``texts`` in batches of 32.

        Args:
            texts: Raw texts (the model prefix is added here).
            kind: ``"query"`` or ``"passage"``.

        Returns:
            Array of shape ``(len(texts), dim)``, ``float32``.

        Raises:
            EncoderError: Unreachable after the last retry, an HTTP error, or a wrong answer.
        """
        inputs = build_embed_request(texts, self._cfg, kind)
        cut = sum(1 for text in inputs if self._count(text) > self._cfg.max_input_tokens)
        if cut:
            self.truncated += cut
            _log.info("embedding_truncated passages=%d limit=%d", cut, self._cfg.max_input_tokens)
        rows: list[list[float]] = []
        for start in range(0, len(inputs), BATCH):
            rows.extend(self._embed(inputs[start : start + BATCH]))
        out = np.asarray(rows, dtype=np.float32)
        if out.shape != (len(texts), self._cfg.dim):
            msg = f"embedding shape {out.shape}, expected {(len(texts), self._cfg.dim)}"
            raise EncoderError(msg)
        return out

    def _embed(self, batch: list[str]) -> list[list[float]]:
        raise NotImplementedError

    def _post(self, body: dict[str, Any]) -> Any:  # noqa: ANN401  (JSON of either API)
        last = ""
        for attempt in range(1, ATTEMPTS + 1):
            try:
                resp = self._client.post(self._url, json=body, headers=self._headers)
            except httpx.HTTPError as err:
                last = f"unreachable ({type(err).__name__})"
            else:
                if resp.status_code == httpx.codes.OK:
                    return _json(resp)
                if resp.status_code not in RETRY_STATUS:
                    msg = f"embedding service returned HTTP {resp.status_code}"
                    raise EncoderError(msg)
                last = f"returned HTTP {resp.status_code}"
            if attempt < ATTEMPTS:
                self._sleep(0.5 * 2 ** (attempt - 1))
        msg = f"embedding service {last} after {ATTEMPTS} attempts"
        raise EncoderError(msg)


def _json(resp: httpx.Response) -> Any:  # noqa: ANN401  (JSON of either API)
    try:
        return resp.json()
    except ValueError:
        msg = "embedding service answered with invalid JSON"
        raise EncoderError(msg) from None


class TeiDenseEncoder(_HttpEncoder):
    """Embed texts through a Text Embeddings Inference server (CPU, tier 1).

    Args:
        cfg: Model entry (prefixes, input limit, vector size, key variable name).
        base_url: TEI base URL, e.g. ``http://localhost:8090``.
        client: Optional ``httpx.Client`` (tests).
        timeout_s: Request timeout.
        sleep: Backoff sleep (tests pass a no-op).
        count_tokens: Token counter for ``truncated`` (default: word lower bound).

    Attributes:
        truncated: Passages longer than the model limit seen so far (TEI cuts them).
    """

    def __init__(
        self,
        cfg: EmbedCfg,
        base_url: str,
        *,
        client: httpx.Client | None = None,
        timeout_s: float = 180.0,
        sleep: Callable[[float], None] = time.sleep,
        count_tokens: TokenCounter | None = None,
    ) -> None:
        super().__init__(
            cfg,
            f"{base_url.rstrip('/')}/embed",
            client=client,
            timeout_s=timeout_s,
            sleep=sleep,
            count_tokens=count_tokens,
        )

    def _embed(self, batch: list[str]) -> list[list[float]]:
        body = {"inputs": batch, "truncate": True, "normalize": True}
        rows: list[list[float]] = self._post(body)
        return rows


class OllamaDenseEncoder(_HttpEncoder):
    """Embed texts through Ollama's native ``/api/embed`` (tier 2, ``bge-m3``).

    The body is ``{model: <bare tag>, input: [...], truncate: true, options}`` and never carries
    ``keep_alive``. ``options`` are the catalogue entry's options (``num_ctx`` equals
    ``max_input_tokens``). Vectors are checked and normalised to unit length.

    Args:
        cfg: Model entry (``model`` is the bare tag, D221).
        base_url: ``OLLAMA_GPU0_URL`` (dev stack) or ``LLM_PROXY_URL`` (gate runs), without ``/v1``.
        options: Catalogue options to send (default: ``cfg.options``).
        count_tokens: Counter built from the model's ``tokenizer.json`` (default: word lower bound).
        client: Optional ``httpx.Client`` (tests).
        timeout_s: Request timeout.
        sleep: Backoff sleep (tests pass a no-op).

    Raises:
        ConfigError: ``options.num_ctx`` differs from ``cfg.max_input_tokens``.
    """

    def __init__(
        self,
        cfg: EmbedCfg,
        base_url: str,
        *,
        options: Mapping[str, int | float] | None = None,
        count_tokens: TokenCounter | None = None,
        client: httpx.Client | None = None,
        timeout_s: float = 180.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        super().__init__(
            cfg,
            f"{base_url.rstrip('/')}/api/embed",
            client=client,
            timeout_s=timeout_s,
            sleep=sleep,
            count_tokens=count_tokens,
        )
        self._options = dict(cfg.options if options is None else options)
        if self._options.get("num_ctx") != cfg.max_input_tokens:
            msg = f"options.num_ctx must equal embed.max_input_tokens ({cfg.max_input_tokens})"
            raise ConfigError(msg)

    def _embed(self, batch: list[str]) -> list[list[float]]:
        body = {
            "model": self._cfg.model,
            "input": batch,
            "truncate": True,
            "options": self._options,
        }
        data = self._post(body)
        rows = data.get("embeddings") if isinstance(data, dict) else None
        if not isinstance(rows, list) or len(rows) != len(batch):
            msg = "Ollama /api/embed answered without one embedding per input"
            raise EncoderError(msg)
        return _unit_rows(rows, self._cfg.dim)


def _unit_rows(rows: list[list[float]], dim: int) -> list[list[float]]:
    arr = np.asarray(rows, dtype=np.float64)
    if arr.ndim != 2 or arr.shape[1] != dim:
        msg = f"Ollama embedding has dimension {arr.shape[-1] if arr.ndim else 0}, expected {dim}"
        raise EncoderError(msg)
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    if not np.all(norms > 0):
        msg = "Ollama returned a zero embedding"
        raise EncoderError(msg)
    unit: list[list[float]] = (arr / norms).tolist()
    return unit
