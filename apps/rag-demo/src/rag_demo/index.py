"""Corpus reader and ``Indexer``: one Qdrant collection with dense and sparse vectors."""

import json
import logging
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
from jsonschema import Draft202012Validator

from rag_demo.analysis import GermanAnalyzer
from rag_demo.errors import CorpusError, RetrievalError
from rag_demo.protocols import DenseEncoder
from rag_demo.sparse import SparseEncoder

_log = logging.getLogger(__name__)
NAMESPACE = uuid.UUID("6f1a8f64-3c1e-4b0e-9d52-5f0b7b1c2a10")
BATCH = 16


def point_id(chunk_id: str) -> str:
    """Return the stable Qdrant point id (UUID5) of a chunk id."""
    return str(uuid.uuid5(NAMESPACE, chunk_id))


def index_text(row: dict[str, Any]) -> str:
    """Text that is embedded and tokenised: the citation key first, so "§ 622 BGB" is findable."""
    key = row.get("citation_key")
    return f"{key}\n{row['text']}" if key else str(row["text"])


def read_corpus(
    corpus_dir: Path, schema_path: Path | None = None
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Read ``manifest.json`` and every ``*.chunks.jsonl``, validating each row against the schema.

    Args:
        corpus_dir: ``corpus/<version>/``.
        schema_path: ``schemas/chunk.schema.json`` (default: two levels above ``corpus_dir``).

    Returns:
        ``(manifest, rows)`` with rows in file-name then line order.

    Raises:
        CorpusError: Missing file, invalid JSON or a row that violates the schema.
    """
    schema_file = schema_path or corpus_dir.parents[1] / "schemas" / "chunk.schema.json"
    try:
        validator = Draft202012Validator(json.loads(schema_file.read_text(encoding="utf-8")))
        manifest = json.loads((corpus_dir / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        msg = f"cannot read corpus metadata: {err}"
        raise CorpusError(msg) from err
    return manifest, list(_rows(corpus_dir, validator))


def _rows(corpus_dir: Path, validator: Draft202012Validator) -> Iterator[dict[str, Any]]:
    for path in sorted(corpus_dir.glob("*.chunks.jsonl")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            row = json.loads(line)
            errors = sorted(e.message for e in validator.iter_errors(row))
            if errors:
                msg = f"{path.name}:{number}: {errors[0]}"
                raise CorpusError(msg)
            yield row


class Indexer:
    """Build the collection ``collection`` from a corpus directory (rebuilds it from scratch).

    Args:
        qdrant_url: Qdrant REST base URL.
        dense: Passage encoder.
        analyzer: Tokeniser for the sparse leg.
        sparse: Sparse encoder.
        collection: Collection name.
        client: Optional ``httpx.Client``.
    """

    def __init__(
        self,
        qdrant_url: str,
        dense: DenseEncoder,
        analyzer: GermanAnalyzer,
        sparse: SparseEncoder,
        *,
        collection: str,
        client: httpx.Client | None = None,
    ) -> None:
        self._base = qdrant_url.rstrip("/")
        self._dense = dense
        self._analyzer = analyzer
        self._sparse = sparse
        self._collection = collection
        self._client = client or httpx.Client(timeout=120)

    def index(self, corpus_dir: Path) -> None:
        """Create the collection, the ``tenant_id`` payload index and all points.

        Args:
            corpus_dir: Directory with ``manifest.json`` and ``<tenant>.chunks.jsonl`` files.

        Raises:
            CorpusError: Invalid corpus files.
            RetrievalError: Qdrant refused a request.
        """
        manifest, rows = read_corpus(corpus_dir)
        dim = int(self._dense.encode(["dim probe"], kind="passage").shape[1])
        self._call("DELETE", "", ok=(200, 404))
        self._call(
            "PUT",
            "",
            json={
                "vectors": {"dense": {"size": dim, "distance": "Cosine"}},
                "sparse_vectors": {"sparse": {"modifier": "idf"}},
                "metadata": {
                    "corpus_version": manifest["corpus_version"],
                    "tenants": sorted(manifest["tenants"]),
                },
            },
        )
        self._call("PUT", "/index", json={"field_name": "tenant_id", "field_schema": "keyword"})
        for start in range(0, len(rows), BATCH):
            self._upsert(rows[start : start + BATCH])
        _log.info("indexed chunks=%d corpus=%s", len(rows), manifest["corpus_version"])

    def _upsert(self, rows: list[dict[str, Any]]) -> None:
        texts = [index_text(r) for r in rows]
        vectors = self._dense.encode(texts, kind="passage")
        points = []
        for row, text, vector in zip(rows, texts, vectors, strict=True):
            sparse = self._sparse.encode(self._analyzer.tokens(text))
            points.append(
                {
                    "id": point_id(row["chunk_id"]),
                    "vector": {
                        "dense": vector.tolist(),
                        "sparse": {"indices": sparse.indices, "values": sparse.values},
                    },
                    "payload": {
                        "chunk_id": row["chunk_id"],
                        "doc_id": row["doc_id"],
                        "tenant_id": row["tenant"],
                        "text": row["text"],
                        "citation_key": row["citation_key"],
                        "section": row["section"],
                        "lang": row["lang"],
                    },
                }
            )
        self._call("PUT", "/points", params={"wait": "true"}, json={"points": points})

    def _call(
        self,
        method: str,
        suffix: str,
        *,
        ok: tuple[int, ...] = (200,),
        **kwargs: Any,  # noqa: ANN401  (forwarded to httpx)
    ) -> None:
        url = f"{self._base}/collections/{self._collection}{suffix}"
        try:
            resp = self._client.request(method, url, **kwargs)
        except httpx.HTTPError as err:
            msg = f"qdrant unreachable ({type(err).__name__})"
            raise RetrievalError(msg) from None
        if resp.status_code not in ok:
            detail = resp.text[:200]
            msg = f"qdrant {method} {suffix or '/'} returned HTTP {resp.status_code}: {detail}"
            raise RetrievalError(msg)
