"""verify_corpus (T2.5): every way a written corpus directory can be tampered with."""

import hashlib
import json
from collections.abc import Callable
from pathlib import Path

import pytest
from testsupport.corpus_support import REPO_ROOT, build_raw_root

from pruefstand.core.config import CorpusBuildConfig
from pruefstand.core.config_loader import load_model
from pruefstand.core.errors import DatasetError
from pruefstand.core.fingerprint import corpus_version
from pruefstand.core.ids import TenantId
from pruefstand.core.models.corpus import Chunk, CorpusManifest
from pruefstand.ingest import corpus_files
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


def forge(
    src: Path,
    dest: Path,
    edit: Callable[[dict[str, list[str]]], None],
    manifest_edit: Callable[[CorpusManifest], CorpusManifest] | None = None,
) -> Path:
    """Rewrite a corpus consistently: files, sha256, counts and version recomputed, dir renamed."""
    manifest = CorpusManifest.model_validate_json((src / "manifest.json").read_bytes())
    lines: dict[str, list[str]] = {
        t: (src / f"{t}.chunks.jsonl").read_text("utf-8").splitlines() for t in manifest.tenants
    }
    edit(lines)
    files = {f"{t}.chunks.jsonl": "".join(f"{x}\n" for x in ls).encode() for t, ls in lines.items()}
    forged = manifest.model_copy(
        update={
            "tenants": {t: len(ls) for t, ls in lines.items()},
            "sha256": {n: hashlib.sha256(d).hexdigest() for n, d in files.items()},
        }
    )
    if manifest_edit:
        forged = manifest_edit(forged)
    version = corpus_version(forged, DATE)
    forged = forged.model_copy(update={"corpus_version": version})
    target = dest / version
    target.mkdir(parents=True)
    for name, data in files.items():
        (target / name).write_bytes(data)
    (target / "manifest.json").write_text(forged.model_dump_json(), encoding="utf-8")
    return target


def check(directory: Path) -> str:
    with pytest.raises(DatasetError) as caught:
        verify_corpus(directory)
    return str(caught.value)


def test_a_forged_but_consistent_corpus_without_edits_verifies(
    written: Path, tmp_path: Path
) -> None:
    assert verify_corpus(forge(written, tmp_path / "f", lambda _lines: None)).tenants


def test_verify_detects_a_chunk_in_the_wrong_tenant_file(written: Path, tmp_path: Path) -> None:
    moved: dict[str, str] = {}

    def edit(lines: dict[str, list[str]]) -> None:
        line = lines["kanzlei_mueller"].pop()
        moved["id"] = json.loads(line)["chunk_id"]
        moved["n"] = str(len(lines["shared_public"]) + 1)
        lines["shared_public"].append(line)

    directory = forge(written, tmp_path / "f", edit)
    expected = (
        f"shared_public.chunks.jsonl:{moved['n']}: chunk {moved['id']} has tenant 'kanzlei_mueller'"
    )
    assert check(directory) == expected


def _copy_into_shared(lines: dict[str, list[str]], **changes: str) -> dict[str, str]:
    record = json.loads(lines["kanzlei_mueller"][0])
    copy = {**record, "tenant": "shared_public", **changes}
    lines["shared_public"].append(json.dumps(copy, sort_keys=True))
    return {"n": str(len(lines["shared_public"])), "chunk": copy["chunk_id"], "doc": copy["doc_id"]}


def test_verify_detects_a_repeated_chunk_id(written: Path, tmp_path: Path) -> None:
    info: dict[str, str] = {}
    directory = forge(
        written,
        tmp_path / "f",
        lambda lines: info.update(_copy_into_shared(lines, doc_id="other-doc")),
    )
    where = f"shared_public.chunks.jsonl:{info['n']}"
    expected = f"{where}: chunk {info['chunk']} or document {info['doc']} repeats"
    assert check(directory) == expected


def test_verify_detects_a_document_in_two_tenants(written: Path, tmp_path: Path) -> None:
    info: dict[str, str] = {}
    directory = forge(
        written,
        tmp_path / "f",
        lambda lines: info.update(_copy_into_shared(lines, chunk_id="new-id")),
    )
    expected = (
        f"shared_public.chunks.jsonl:{info['n']}: chunk new-id or document {info['doc']} repeats"
    )
    assert check(directory) == expected


def test_verify_detects_a_wrong_line_count(written: Path, tmp_path: Path) -> None:
    honest = CorpusManifest.model_validate_json((written / "manifest.json").read_bytes())
    n = honest.tenants[TenantId("kanzlei_mueller")]
    directory = forge(
        written,
        tmp_path / "f",
        lambda _lines: None,
        lambda m: m.model_copy(update={"tenants": {**m.tenants, "kanzlei_mueller": n + 1}}),
    )
    assert check(directory) == f"kanzlei_mueller.chunks.jsonl: {n} lines, the manifest says {n + 1}"


def test_verify_detects_sha256_keys_that_do_not_match_the_tenants(
    written: Path, tmp_path: Path
) -> None:
    directory = forge(
        written,
        tmp_path / "f",
        lambda _lines: None,
        lambda m: m.model_copy(update={"sha256": {**m.sha256, "ghost.chunks.jsonl": "0" * 64}}),
    )
    assert check(directory) == "manifest.json: sha256 keys do not match the tenants"


def test_verify_detects_a_corpus_version_that_does_not_match_the_content(
    written: Path, tmp_path: Path
) -> None:
    directory = forge(written, tmp_path / "f", lambda _lines: None)
    manifest = CorpusManifest.model_validate_json((directory / "manifest.json").read_bytes())
    changed = manifest.model_copy(update={"sources": {**manifest.sources, "gii:other": "x"}})
    (directory / "manifest.json").write_text(changed.model_dump_json(), encoding="utf-8")
    expected = (
        f"corpus_version {manifest.corpus_version} does not match the content "
        f"({corpus_version(changed, DATE)})"
    )
    assert check(directory) == expected


def test_verify_refuses_an_oversized_manifest(written: Path) -> None:
    (written / "manifest.json").write_bytes(b" " * (2 * 1024 * 1024))
    with pytest.raises(DatasetError, match="manifest"):
        verify_corpus(written)


# --- T2.5a: the writer's own rules, sorted order, one pass, the tenant plan ---------------------
def edited_line(lines: dict[str, list[str]], tenant: str, **changes: object) -> None:
    lines[tenant][0] = json.dumps({**json.loads(lines[tenant][0]), **changes}, sort_keys=True)


def test_verify_applies_the_writers_licence_rule(written: Path, tmp_path: Path) -> None:
    directory = forge(
        written, tmp_path / "f", lambda ls: edited_line(ls, "kanzlei_mueller", license=" ")
    )
    message = check(directory)
    assert message.startswith("kanzlei_mueller.chunks.jsonl:1: chunk ")
    assert "license is empty" in message


def test_verify_applies_the_writers_banned_source_rule(written: Path, tmp_path: Path) -> None:
    directory = forge(
        written, tmp_path / "f", lambda ls: edited_line(ls, "kanzlei_mueller", source="memerag:x")
    )
    assert "banned" in check(directory)


def test_verify_detects_chunks_out_of_order(written: Path, tmp_path: Path) -> None:
    def edit(lines: dict[str, list[str]]) -> None:
        lines["shared_public"][0], lines["shared_public"][1] = (
            lines["shared_public"][1],
            lines["shared_public"][0],
        )

    message = check(forge(written, tmp_path / "f", edit))
    assert message == "shared_public.chunks.jsonl:2: chunks are not sorted by (doc_id, chunk_id)"


def test_a_changed_byte_is_a_hash_error_even_when_the_line_no_longer_parses(
    written: Path,
) -> None:
    path = written / "shared_public.chunks.jsonl"
    data = path.read_bytes()
    path.write_bytes(b"{broken" + data[7:])  # first line is no chunk any more, hash differs
    with pytest.raises(DatasetError, match="sha256 does not match"):
        verify_corpus(written)


def test_verify_reads_each_tenant_file_once(written: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[str] = []
    real = corpus_files.open_regular

    def counting(path: Path) -> int:
        opened.append(path.name)
        return real(path)

    monkeypatch.setattr(corpus_files, "open_regular", counting)
    verify_corpus(written)
    tenant_reads = [n for n in opened if n.endswith(".chunks.jsonl")]
    assert sorted(tenant_reads) == sorted(set(tenant_reads))


def test_verify_accepts_the_plan_the_corpus_was_built_with(written: Path) -> None:
    assert verify_corpus(written, PLAN).tenants


def test_verify_detects_a_chunk_in_a_tenant_the_plan_does_not_give_its_source(
    written: Path, tmp_path: Path
) -> None:
    def edit(lines: dict[str, list[str]]) -> None:
        line = lines["kanzlei_mueller"].pop(0)
        lines["versicherung_nord"].insert(
            0, json.dumps({**json.loads(line), "tenant": "versicherung_nord"}, sort_keys=True)
        )

    directory = forge(written, tmp_path / "f", edit)
    with pytest.raises(DatasetError, match=r"belongs to \['kanzlei_mueller'\]"):
        verify_corpus(directory, PLAN)


def test_verify_detects_a_tenant_the_plan_does_not_declare(written: Path) -> None:
    smaller = PLAN.model_copy(
        update={
            "tenants": tuple(t for t in PLAN.tenants if t != "shared_public"),
            "rules": tuple(r for r in PLAN.rules if r.tenant != "shared_public"),
        }
    )
    with pytest.raises(DatasetError, match="not declared by the plan"):
        verify_corpus(written, smaller)
