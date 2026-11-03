"""``QdrantStore``: the two Qdrant REST calls the retriever makes (query, collection metadata).

The API key (``QDRANT_API_KEY``) is sent as the ``api-key`` header when set; it never appears in
an error message.
"""

import httpx

from rag_demo.errors import RetrievalError
from rag_demo.retrieval.query_builder import QdrantQuery

TIMEOUT_S = 30.0


class QdrantStore:
    """Read-only Qdrant client for one collection (or alias).

    Args:
        base_url: Qdrant REST base URL.
        collection: Collection or alias name (``chunks_active``).
        api_key: Optional API key.
        client: Optional ``httpx.Client`` (tests record the requests through its transport).
    """

    def __init__(
        self,
        base_url: str,
        collection: str,
        *,
        api_key: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self._url = f"{base_url.rstrip('/')}/collections/{collection}"
        self._key = api_key or None
        self._headers = {"api-key": self._key} if self._key else {}
        self._client = client or httpx.Client(timeout=TIMEOUT_S)

    def _call(
        self, method: str, path: str, body: dict[str, object] | None = None
    ) -> httpx.Response:
        try:
            resp = self._client.request(method, self._url + path, headers=self._headers, json=body)
        except httpx.HTTPError as err:
            msg = f"qdrant unreachable ({type(err).__name__})"
            raise RetrievalError(msg) from None
        if resp.status_code != httpx.codes.OK:
            msg = f"qdrant {method} {path or '/'} returned HTTP {resp.status_code}"
            raise RetrievalError(msg)
        return resp

    def query(self, request: QdrantQuery) -> list[object]:
        """Run one Query API request and return its ``points``.

        Raises:
            RetrievalError: Qdrant is unreachable, answers with an error, or in another shape.
        """
        resp = self._call("POST", "/points/query", request.to_json())
        try:
            points = resp.json()["result"]["points"]
        except (KeyError, TypeError, ValueError):
            msg = "qdrant answered with an unexpected body"
            raise RetrievalError(msg) from None
        if not isinstance(points, list):
            msg = "qdrant answered with an unexpected body"
            raise RetrievalError(msg)
        return points

    def metadata(self) -> dict[str, object]:
        """The collection metadata (``result.config.metadata``).

        Raises:
            RetrievalError: Qdrant is unreachable, answers with an error, or in another shape.
        """
        resp = self._call("GET", "")
        try:
            meta = resp.json()["result"]["config"]["metadata"]
        except (KeyError, TypeError, ValueError):
            msg = "qdrant collection has no metadata"
            raise RetrievalError(msg) from None
        if not isinstance(meta, dict):
            msg = "qdrant collection has no metadata"
            raise RetrievalError(msg)
        return meta
