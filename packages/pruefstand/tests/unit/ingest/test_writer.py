"""write_corpus and verify_corpus (T2.5): deterministic files, manifest, and tamper checks."""

import hashlib
import json
import os
import random
import time
from pathlib import Path

import pytest
from testsupport.corpus_support import REPO_ROOT, build_raw_root

from pruefstand.core.config import CorpusBuildConfig
from pruefstand.core.config_loader import load_model
from pruefstand.core.errors import DatasetError
from pruefstand.core.fingerprint import corpus_version
from pruefstand.core.ids import ChunkId, DocId, TenantId
from pruefstand.core.models.corpus import Chunk, CorpusManifest
from pruefstand.ingest.chunkers.paragraph import ParagraphChunker
from pruefstand.ingest.gii_xml import GiiXmlLoader
from pruefstand.ingest.tenants import assign_tenants
from pruefstand.ingest.writer import (
    provisional_manifest,
    serialise_chunk,
    verify_corpus,
    write_corpus,
)

PLAN = load_model(REPO_ROOT / "corpus.yaml", CorpusBuildConfig).plan
SOURCES = {"gii:bgb": "2026-10-31", "gii:kschg": "2026-10-31"}
DATE = "2026-11-02"


@pytest.fixture(scope="module")
def chunks(tmp_path_factory: pytest.TempPathFactory) -> list[Chunk]:
    raw = build_raw_root(tmp_path_factory.mktemp("raw"))
    docs = assign_tenants(GiiXmlLoader().load(raw / "gii"), PLAN)
    out = [c for doc in docs for c in ParagraphChunker().chunk(doc)]
    assert len({c.tenant for c in out}) == 3
    return out


def version_of(items: list[Chunk]) -> str:
    return corpus_version(provisional_manifest(items, SOURCES), DATE)


def write(items: list[Chunk], out: Path, sources: dict[str, str] | None = None) -> CorpusManifest:
    return write_corpus(
        items, out / version_of(items), version_of(items), sources=sources or SOURCES
    )


def snapshot(directory: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(directory.iterdir())}


def clone(chunk: Chunk, **changes: object) -> Chunk:
    return chunk.model_copy(update=changes)


def test_writing_twice_gives_identical_bytes_and_version(
    chunks: list[Chunk], tmp_path: Path
) -> None:
    one, two = write(chunks, tmp_path / "a"), write(chunks, tmp_path / "b")
    assert one == two
    assert snapshot(tmp_path / "a" / one.corpus_version) == snapshot(
        tmp_path / "b" / two.corpus_version
    )


def test_shuffled_input_gives_identical_output(chunks: list[Chunk], tmp_path: Path) -> None:
    shuffled = list(chunks)
    random.Random(7).shuffle(shuffled)
    one, two = write(chunks, tmp_path / "a"), write(shuffled, tmp_path / "b")
    assert one.corpus_version == two.corpus_version
    assert snapshot(tmp_path / "a" / one.corpus_version) == snapshot(
        tmp_path / "b" / two.corpus_version
    )


def test_lines_are_sorted_by_tenant_doc_and_chunk(chunks: list[Chunk], tmp_path: Path) -> None:
    manifest = write(list(reversed(chunks)), tmp_path)
    for tenant in manifest.tenants:
        path = tmp_path / manifest.corpus_version / f"{tenant}.chunks.jsonl"
        keys = [
            (c["doc_id"], c["chunk_id"])
            for c in map(json.loads, path.read_text(encoding="utf-8").splitlines())
        ]
        assert keys == sorted(keys)


def test_manifest_counts_hashes_and_version(chunks: list[Chunk], tmp_path: Path) -> None:
    manifest = write(chunks, tmp_path)
    directory = tmp_path / manifest.corpus_version
    for tenant, count in manifest.tenants.items():
        data = (directory / f"{tenant}.chunks.jsonl").read_bytes()
        assert len(data.splitlines()) == count == sum(1 for c in chunks if c.tenant == tenant)
        assert manifest.sha256[f"{tenant}.chunks.jsonl"] == hashlib.sha256(data).hexdigest()
    assert set(manifest.sha256) == {f"{t}.chunks.jsonl" for t in manifest.tenants}
    assert manifest.sources == SOURCES
    assert manifest.corpus_version.startswith(f"{DATE}.")
    assert manifest.created_at.isoformat() == "2026-11-02T00:00:00+00:00"
    on_disk = CorpusManifest.model_validate_json((directory / "manifest.json").read_bytes())
    assert on_disk == manifest
    assert verify_corpus(directory) == manifest


def test_every_line_round_trips_to_the_chunk(chunks: list[Chunk], tmp_path: Path) -> None:
    manifest = write(chunks, tmp_path)
    back = [
        Chunk.model_validate_json(line)
        for t in manifest.tenants
        for line in (tmp_path / manifest.corpus_version / f"{t}.chunks.jsonl")
        .read_text("utf-8")
        .splitlines()
    ]
    assert sorted(back, key=lambda c: c.chunk_id) == sorted(chunks, key=lambda c: c.chunk_id)


def test_umlauts_are_written_as_utf8_and_line_separators_are_escaped(chunks: list[Chunk]) -> None:
    line = serialise_chunk(clone(chunks[0], text="Kündigung neu \u0085 ende\r\nx"))
    assert "Kündigung".encode() in line
    assert line.endswith(b"\n") and line.count(b"\n") == 1
    text = line.decode("utf-8")
    assert not any(ch in text[:-1] for ch in (" ", " ", "\u0085", "\r"))
    assert json.loads(text)["text"] == "Kündigung neu \u0085 ende\r\nx"


def test_a_lone_surrogate_is_a_dataset_error_naming_the_chunk(chunks: list[Chunk]) -> None:
    bad = clone(chunks[0], text="a\ud800b")
    with pytest.raises(DatasetError, match=str(bad.chunk_id)):
        serialise_chunk(bad)


def test_a_wrong_corpus_version_is_refused_and_nothing_is_written(
    chunks: list[Chunk], tmp_path: Path
) -> None:
    wrong = f"{DATE}.00000000"
    with pytest.raises(DatasetError, match="corpus_version"):
        write_corpus(chunks, tmp_path / wrong, wrong, sources=SOURCES)
    assert list(tmp_path.iterdir()) == []


def test_a_version_that_changes_with_the_sources(chunks: list[Chunk]) -> None:
    other = corpus_version(provisional_manifest(chunks, {"gii:bgb": "2026-11-01"}), DATE)
    assert other != version_of(chunks)


def test_a_chunk_id_twice_is_refused(chunks: list[Chunk], tmp_path: Path) -> None:
    with pytest.raises(DatasetError, match=str(chunks[0].chunk_id)):
        provisional_manifest([*chunks, chunks[0]], SOURCES)


def test_a_doc_in_two_tenants_is_refused(chunks: list[Chunk]) -> None:
    other = clone(
        chunks[0],
        tenant=TenantId(
            "shared_public" if chunks[0].tenant != "shared_public" else "kanzlei_mueller"
        ),
        chunk_id=ChunkId("elsewhere"),
    )
    with pytest.raises(DatasetError, match=str(chunks[0].doc_id)):
        provisional_manifest([*chunks, other], SOURCES)


@pytest.mark.parametrize(
    "tenant", ["../evil", "a/b", "A", "", "unassigned", "x" * 80, "ten ant", "é", "a\x00b"]
)
def test_an_unsafe_tenant_id_never_reaches_the_file_system(
    chunks: list[Chunk], tmp_path: Path, tenant: str
) -> None:
    bad = clone(chunks[0], tenant=TenantId(tenant), chunk_id=ChunkId("zz"), doc_id=DocId("zz-doc"))
    with pytest.raises(DatasetError, match="tenant"):
        write_corpus([*chunks, bad], tmp_path / "v", f"{DATE}.00000000", sources=SOURCES)
    assert list(tmp_path.iterdir()) == []


def test_a_chunk_without_a_license_is_refused(chunks: list[Chunk]) -> None:
    with pytest.raises(DatasetError, match="license"):
        provisional_manifest([clone(chunks[0], license=" ")], SOURCES)


def test_a_banned_source_is_refused(chunks: list[Chunk]) -> None:
    with pytest.raises(DatasetError, match="memerag"):
        provisional_manifest([clone(chunks[0], source="memerag:x")], SOURCES)


@pytest.mark.parametrize(
    "version", ["../x", "2026-11-02", "2026-11-02.zzzzzzzz", "2026-11-02.abc/def", ""]
)
def test_a_malformed_corpus_version_is_refused(
    chunks: list[Chunk], tmp_path: Path, version: str
) -> None:
    with pytest.raises(DatasetError, match="corpus_version"):
        write_corpus(chunks, tmp_path / "v", version, sources=SOURCES)


def test_rewriting_the_same_corpus_is_allowed_a_different_one_is_not(
    chunks: list[Chunk], tmp_path: Path
) -> None:
    manifest = write(chunks, tmp_path)
    assert write(chunks, tmp_path) == manifest
    directory = tmp_path / manifest.corpus_version
    (directory / "kanzlei_mueller.chunks.jsonl").write_bytes(b"{}\n")
    with pytest.raises(DatasetError, match="already exists"):
        write(chunks, tmp_path)
    assert (directory / "kanzlei_mueller.chunks.jsonl").read_bytes() == b"{}\n"


def test_a_symlinked_output_directory_is_refused(chunks: list[Chunk], tmp_path: Path) -> None:
    target = tmp_path / "elsewhere"
    target.mkdir()
    link = tmp_path / "out"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(DatasetError, match="symlink"):
        write(chunks, link)
    assert list(target.iterdir()) == []


def test_no_staging_directory_is_left_behind_after_a_failure(
    chunks: list[Chunk], tmp_path: Path
) -> None:
    with pytest.raises(DatasetError):
        write_corpus(chunks, tmp_path / "bad", "nonsense", sources=SOURCES)
    assert list(tmp_path.iterdir()) == []


def test_a_stale_staging_directory_is_replaced(chunks: list[Chunk], tmp_path: Path) -> None:
    version = version_of(chunks)
    stale = tmp_path / f".{version}.partial"
    stale.mkdir()
    (stale / "junk").write_text("x", encoding="utf-8")
    write(chunks, tmp_path)
    assert not stale.exists()


# --- verify_corpus ---------------------------------------------------------------------------


@pytest.fixture
def written(chunks: list[Chunk], tmp_path: Path) -> Path:
    return tmp_path / write(chunks, tmp_path).corpus_version


def test_verify_detects_a_changed_byte(written: Path) -> None:
    path = written / "shared_public.chunks.jsonl"
    data = bytearray(path.read_bytes())
    data[10] ^= 1
    path.write_bytes(bytes(data))
    with pytest.raises(DatasetError, match="sha256"):
        verify_corpus(written)


def test_verify_detects_a_missing_and_an_extra_file(written: Path) -> None:
    (written / "extra.chunks.jsonl").write_text("{}\n", encoding="utf-8")
    with pytest.raises(DatasetError, match="extra.chunks.jsonl"):
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
    with pytest.raises(DatasetError, match="symlink|regular"):
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
    with pytest.raises(DatasetError, match="tenant|corpus_version"):
        verify_corpus(written)


def test_verify_refuses_an_oversized_manifest(written: Path) -> None:
    (written / "manifest.json").write_bytes(b" " * (2 * 1024 * 1024))
    with pytest.raises(DatasetError, match="manifest"):
        verify_corpus(written)


def test_writing_scales_linearly(chunks: list[Chunk], tmp_path: Path) -> None:
    def many(factor: int) -> list[Chunk]:
        return [
            clone(c, chunk_id=ChunkId(f"{c.chunk_id}#{i}"), doc_id=DocId(f"{c.doc_id}#{i}"))
            for i in range(factor)
            for c in chunks
        ]

    def timed(items: list[Chunk], name: str) -> float:
        start = time.perf_counter()
        write(items, tmp_path / name)
        return time.perf_counter() - start

    small, large = many(100), many(400)
    ratio = timed(large, "large") / max(timed(small, "small"), 1e-6)
    assert ratio < 12 and os.path.isdir(tmp_path)
