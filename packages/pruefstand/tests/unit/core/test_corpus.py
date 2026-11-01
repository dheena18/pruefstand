from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from pruefstand.core.enums import Lang
from pruefstand.core.ids import ChunkId, DocId, TenantId
from pruefstand.core.models.corpus import Chunk, CorpusManifest, Document


def chunk() -> Chunk:
    return Chunk(
        chunk_id=ChunkId("bgb-622#0"),
        doc_id=DocId("bgb-622"),
        tenant=TenantId("kanzlei_mueller"),
        lang=Lang.DE,
        text="Die „Kündigung“ bedarf der Schriftform.",
        citation_key="§ 622 BGB",
        section=None,
        parallel_id=None,
        version_date=date(2026, 1, 1),
        license="own",
        source="gii",
    )


def test_chunk_round_trip_keeps_nfc_text() -> None:
    c = chunk()
    again = Chunk.model_validate_json(c.model_dump_json())
    assert again == c
    assert again.text == "Die „Kündigung“ bedarf der Schriftform."
    assert again.is_attack is False
    assert again.citation_key == "§ 622 BGB"


def test_document_round_trip() -> None:
    doc = Document(
        doc_id=DocId("bgb-622"),
        tenant=TenantId("kanzlei_mueller"),
        source="gii",
        lang=Lang.DE,
        title="§ 622 BGB",
        law_abbrev="BGB",
        version_date=None,
        text="Kündigungsfristen",
        license="own",
        url=None,
    )
    assert doc.metadata == {}
    assert Document.model_validate_json(doc.model_dump_json()) == doc


def manifest_data() -> dict[str, object]:
    return {
        "corpus_version": "2026-11-02.ab12cd34",
        "created_at": datetime(2026, 11, 2, tzinfo=UTC),
        "sources": {"gii": "2026-10-01"},
        "tenants": {"kanzlei_mueller": 3},
        "sha256": {"a.jsonl": "00" * 32},
    }


def test_manifest_round_trip() -> None:
    manifest = CorpusManifest.model_validate(manifest_data())
    assert CorpusManifest.model_validate_json(manifest.model_dump_json()) == manifest


def test_manifest_extra_field_is_an_error() -> None:
    with pytest.raises(ValidationError, match="extra"):
        CorpusManifest.model_validate({**manifest_data(), "note": "x"})


def test_chunk_extra_field_is_an_error() -> None:
    with pytest.raises(ValidationError, match="extra"):
        Chunk.model_validate({**chunk().model_dump(), "extra": 1})
