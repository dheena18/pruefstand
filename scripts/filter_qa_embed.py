"""Embedding function of ``scripts/filter_qa.py``: question vectors from a real embedding server.

``tei``: the CPU text-embeddings server of the tier-1 stack (``POST <url>/embed``);
``ollama``: the native ``POST <url>/api/embed`` (D219). No credential is sent or read here.
"""

from collections.abc import Callable, Sequence
from typing import Literal

import httpx
import numpy as np
from numpy.typing import NDArray

from pruefstand.core.errors import DatasetError

BATCH = 32
TIMEOUT_S = 60.0
Embedder = Callable[[Sequence[str]], NDArray[np.float32]]


def _post(client: httpx.Client, url: str, body: dict[str, object]) -> object:
    try:
        response = client.post(url, json=body)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        msg = f"embedding request failed ({type(exc).__name__})"
        raise DatasetError(msg) from exc


def make_embedder(
    url: str,
    api: Literal["tei", "ollama"],
    model: str,
    *,
    client: httpx.Client | None = None,
) -> Embedder:
    """Return a function that embeds texts in batches of 32.

    Args:
        url: Base URL of the embedding server.
        api: ``tei`` or ``ollama``.
        model: Model name (``ollama`` only).
        client: HTTP client (tests); default a new one with a 60 s timeout.

    Raises:
        DatasetError: (when called) the server is unreachable or answers something else.
    """
    http = client or httpx.Client(timeout=TIMEOUT_S)
    base = url.rstrip("/")

    def embed(texts: Sequence[str]) -> NDArray[np.float32]:
        rows: list[object] = []
        for start in range(0, len(texts), BATCH):
            batch = list(texts[start : start + BATCH])
            if api == "tei":
                data = _post(http, f"{base}/embed", {"inputs": batch, "truncate": True})
            else:
                body = _post(http, f"{base}/api/embed", {"model": model, "input": batch})
                data = body.get("embeddings") if isinstance(body, dict) else None
            if not isinstance(data, list) or len(data) != len(batch):
                msg = "embedding server answered with an unexpected shape"
                raise DatasetError(msg)
            rows.extend(data)
        return np.asarray(rows, dtype=np.float32).reshape(len(texts), -1)

    return embed
