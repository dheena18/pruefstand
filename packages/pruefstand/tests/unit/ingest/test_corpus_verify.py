"""verify_corpus (T2.5): every way a written corpus directory can be tampered with."""

import hashlib
import json
from pathlib import Path

import pytest
from testsupport.corpus_support import REPO_ROOT, build_raw_root

from pruefstand.core.config import CorpusBuildConfig
from pruefstand.core.config_loader import load_model
from pruefstand.core.errors import DatasetError
from pruefstand.core.fingerprint import corpus_version
from pruefstand.core.models.corpus import Chunk, CorpusManifest
from pruefstand.ingest.chunkers.paragraph import ParagraphChunker
from pruefstand.ingest.corpus_verify import verify_corpus
from pruefstand.ingest.gii_xml import GiiXmlLoader
from pruefstand.ingest.tenants import assign_tenants
from pruefstand.ingest.writer import provisional_manifest, write_corpus

PLAN = load_model(REPO_ROOT / "corpus.yaml", CorpusBuildConfig).plan
SOURCES = {"gii:bgb": "2026-10-31", "gii:kschg": "2026-10-31"}
DATE = "2026-11-02"


@pytest.fixture(scope="module")
def chunks(tmp_path_factory: pytest.TempPathFactory) -> list[Chunk]:
    raw = build_raw_root(tmp_path_factory.mktemp("raw"))
    docs = assign_tenants(GiiXmlLoader().load(raw / "gii"), PLAN)
    return [c for doc in docs for c in ParagraphChunker().chunk(doc)]


@pytest.fixture
def written(chunks: list[Chunk], tmp_path: Path) -> Path:
    version = corpus_version(provisional_manifest(chunks, SOURCES), DATE)
    return (
        tmp_path / write_corpus(chunks, tmp_path / version, version, sources=SOURCES).corpus_version
    )


def test_verify_detects_a_changed_byte(written: Path) -> None:
    path = written / "shared_public.chunks.jsonl"
    data = bytearray(path.read_bytes())
    data[10] ^= 1
    path.write_bytes(bytes(data))
    with pytest.raises(DatasetError, match="sha256"):
        verify_corpus(written)


def test_verify_detects_a_missing_and_an_extra_file(written: Path) -> None:
    (written / "extra.chunks.jsonl").write_text("{}\n", encoding="utf-8")
    with pytest.raises(DatasetError, match=r"extra\.chunks\.jsonl"):
        verify_corpus(written)
    (written / "extra.chunks.jsonl").unlink()
    (written / "shared_public.chunks.jsonl").unlink()
    with pytest.raises(DatasetError, match="shared_public"):
        verify_corpus(written)


def test_verify_refuses_a_symlinked_file(written: Path, tmp_path: Path) -> None:
    path = written / "shared_public.chunks.jsonl"
    copy = tmp_path / "copy.jsonl"
    copy.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(copy)
    with pytest.raises(DatasetError, match=r"symlink|regular"):
        verify_corpus(written)


def test_verify_detects_a_chunk_in_the_wrong_tenant_file(written: Path) -> None:
    manifest = CorpusManifest.model_validate_json((written / "manifest.json").read_bytes())
    path = written / "kanzlei_mueller.chunks.jsonl"
    line = json.loads(path.read_text("utf-8").splitlines()[0])
    line["tenant"] = "shared_public"
    data = (json.dumps(line, sort_keys=True) + "\n").encode()
    path.write_bytes(data)
    bad = manifest.model_copy(
        update={
            "sha256": {**manifest.sha256, path.name: hashlib.sha256(data).hexdigest()},
            "tenants": {**manifest.tenants, "kanzlei_mueller": 1},
        }
    )
    (written / "manifest.json").write_text(bad.model_dump_json(), encoding="utf-8")
    with pytest.raises(DatasetError, match=r"tenant|corpus_version"):
        verify_corpus(written)


def test_verify_refuses_an_oversized_manifest(written: Path) -> None:
    (written / "manifest.json").write_bytes(b" " * (2 * 1024 * 1024))
    with pytest.raises(DatasetError, match="manifest"):
        verify_corpus(written)
