"""Corpus models (interfaces §11): documents, chunks and the corpus manifest."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from pruefstand.core.enums import Lang
from pruefstand.core.ids import ChunkId, DocId, TenantId


class Document(BaseModel):
    """A source document before chunking."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    doc_id: DocId
    tenant: TenantId
    source: str
    lang: Lang
    title: str
    law_abbrev: str | None
    version_date: date | None
    text: str
    license: str
    url: str | None
    metadata: dict[str, str] = {}


class Chunk(BaseModel):
    """One retrievable chunk (one line of ``corpus/<version>/<tenant>.chunks.jsonl``).

    ``citation_key`` is the normalised citation, e.g. ``"§ 622 BGB"``. Text is stored as given
    (no Unicode normalisation).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    chunk_id: ChunkId
    doc_id: DocId
    tenant: TenantId
    lang: Lang
    text: str
    citation_key: str | None
    section: str | None
    parallel_id: str | None
    version_date: date | None
    license: str
    source: str
    is_attack: bool = False


class CorpusManifest(BaseModel):
    """``corpus/<corpus_version>/manifest.json``.

    ``corpus_version`` and ``created_at`` are excluded from ``fingerprint.corpus_version``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    corpus_version: str
    created_at: datetime
    sources: dict[str, str]
    tenants: dict[TenantId, int]
    sha256: dict[str, str]
