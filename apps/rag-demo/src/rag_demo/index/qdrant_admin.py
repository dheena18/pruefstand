"""``QdrantAdmin``: the REST calls the indexer needs (collections, payload indexes, aliases)."""

from typing import Any

import httpx

from rag_demo.errors import RetrievalError

# tenant_id is the tenant key (co-located storage, in-query filter); the others serve filters.
PAYLOAD_INDEXES: tuple[tuple[str, str | dict[str, Any]], ...] = (
    ("tenant_id", {"type": "keyword", "is_tenant": True}),
    ("lang", "keyword"),
    ("doc_id", "keyword"),
    ("is_attack", "bool"),
)


class QdrantAdmin:
    """Thin client for the Qdrant calls of the indexer; errors never contain the API key.

    Args:
        base_url: Qdrant REST base URL.
        api_key: Optional API key, sent as ``api-key`` header (env ``QDRANT_API_KEY``).
        client: Optional ``httpx.Client`` (tests).
    """

    def __init__(
        self, base_url: str, *, api_key: str | None = None, client: httpx.Client | None = None
    ) -> None:
        self._base = base_url.rstrip("/")
        self._key = api_key or None
        self._headers = {"api-key": self._key} if self._key else {}
        self._client = client or httpx.Client(timeout=120)

    def _call(
        self,
        method: str,
        path: str,
        *,
        ok: tuple[int, ...] = (200,),
        **kwargs: Any,  # noqa: ANN401  (forwarded to httpx)
    ) -> httpx.Response:
        try:
            resp = self._client.request(
                method, f"{self._base}{path}", headers=self._headers, **kwargs
            )
        except httpx.HTTPError as err:
            msg = f"qdrant unreachable ({type(err).__name__})"
            raise RetrievalError(msg) from None
        if resp.status_code not in ok:
            detail = resp.text[:200]
            if self._key:
                detail = detail.replace(self._key, "***")
            msg = f"qdrant {method} {path} returned HTTP {resp.status_code}: {detail}"
            raise RetrievalError(msg)
        return resp

    def collection_info(self, name: str) -> dict[str, Any] | None:
        """The ``result`` of ``GET /collections/<name>``, or ``None`` when it does not exist."""
        resp = self._call("GET", f"/collections/{name}", ok=(200, 404))
        if resp.status_code == httpx.codes.NOT_FOUND:
            return None
        result: dict[str, Any] = resp.json()["result"]
        return result

    def alias_target(self, alias: str) -> str | None:
        """The collection ``alias`` points to, or ``None``."""
        aliases = self._call("GET", "/aliases").json()["result"]["aliases"]
        for entry in aliases:
            if entry["alias_name"] == alias:
                return str(entry["collection_name"])
        return None

    def create_collection(self, name: str, dim: int, metadata: dict[str, Any]) -> None:
        """Create ``name`` with the ``dense`` (cosine) and ``sparse`` (idf) vectors and metadata."""
        body = {
            "vectors": {"dense": {"size": dim, "distance": "Cosine"}},
            "sparse_vectors": {"sparse": {"modifier": "idf"}},
            "metadata": metadata,
        }
        self._call("PUT", f"/collections/{name}", json=body)

    def ensure_payload_indexes(self, name: str) -> None:
        """Create the payload indexes (``tenant_id`` is the tenant key); repeating is harmless."""
        for field, schema in PAYLOAD_INDEXES:
            body = {"field_name": field, "field_schema": schema}
            self._call("PUT", f"/collections/{name}/index", params={"wait": "true"}, json=body)

    def upsert(self, name: str, points: list[dict[str, Any]]) -> None:
        """Upsert points (same ids replace the old ones, so a re-run is idempotent)."""
        self._call(
            "PUT", f"/collections/{name}/points", params={"wait": "true"}, json={"points": points}
        )

    def set_metadata(self, name: str, metadata: dict[str, Any]) -> None:
        """Replace the collection metadata (corpus version, fingerprint, avgdl, counters)."""
        self._call("PATCH", f"/collections/{name}", json={"metadata": metadata})

    def apply_aliases(self, actions: list[dict[str, Any]]) -> None:
        """Apply alias ``actions`` in one request, which Qdrant executes atomically."""
        self._call("POST", "/collections/aliases", json={"actions": actions})

    def drop(self, name: str, *, alias: str) -> None:
        """Delete collection ``name``.

        Raises:
            RetrievalError: ``name`` is the collection ``alias`` points to (never drop the active
                index), or Qdrant refuses.
        """
        if self.alias_target(alias) == name:
            msg = f"refusing to drop {name}: it is the active collection ({alias})"
            raise RetrievalError(msg)
        self._call("DELETE", f"/collections/{name}", ok=(200, 404))
