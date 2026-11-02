"""``pruefstand ingest`` end to end on the T2.2-T2.4 fixtures (offline, no marker)."""

import json
from pathlib import Path

import pytest
import yaml
from testsupport.corpus_support import PLAN_FIXTURE, build_raw_root, fixture_config
from typer.testing import CliRunner, Result

from pruefstand.cli import app
from pruefstand.core.config import CorpusBuildConfig
from pruefstand.core.config_loader import load_model
from pruefstand.core.enums import Lang
from pruefstand.core.ids import DocId, TenantId
from pruefstand.core.models.corpus import Chunk, CorpusManifest, Document
from pruefstand.ingest.corpus_verify import verify_corpus
from pruefstand.pipeline import ingest as pipeline_ingest

TENANTS = {"kanzlei_mueller", "versicherung_nord", "stadtwerke_sued", "shared_public"}


def ingest(config: Path, out: Path, *extra: str) -> Result:
    args = ["ingest", "--config", str(config), "--out", str(out), "--date", "2026-11-02", *extra]
    return CliRunner().invoke(app, args)


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path, Result]:
    base = tmp_path_factory.mktemp("ingest")
    raw = build_raw_root(base / "raw")
    config = fixture_config(base, raw)
    return config, base / "out", ingest(config, base / "out")


def chunks_of(directory: Path, tenant: str) -> list[Chunk]:
    path = directory / f"{tenant}.chunks.jsonl"
    return [Chunk.model_validate_json(line) for line in path.read_text("utf-8").splitlines()]


def version_dir(built: tuple[Path, Path, Result]) -> Path:
    (directory,) = (built[1]).iterdir()
    return directory


def test_ingest_writes_four_tenant_files_and_a_dated_version(
    built: tuple[Path, Path, Result],
) -> None:
    result = built[2]
    assert result.exit_code == 0, result.output
    directory = version_dir(built)
    assert directory.name.startswith("2026-11-02.")
    assert {p.name for p in directory.iterdir()} == {
        "manifest.json",
        *(f"{t}.chunks.jsonl" for t in TENANTS),
    }
    manifest = verify_corpus(directory)
    assert manifest.corpus_version == directory.name
    assert set(manifest.tenants) == TENANTS
    assert all(n > 0 for n in manifest.tenants.values())


def test_the_command_prints_the_version_and_the_counts(built: tuple[Path, Path, Result]) -> None:
    manifest = verify_corpus(version_dir(built))
    out = built[2].stdout
    assert f"corpus_version={manifest.corpus_version}" in out
    for tenant, count in manifest.tenants.items():
        assert f"{tenant}: {count}" in out


def test_the_manifest_pins_every_source(built: tuple[Path, Path, Result]) -> None:
    manifest = verify_corpus(version_dir(built))
    assert manifest.sources["gii:kschg"] == "2026-10-31"
    assert manifest.sources["eurlex:32016R0679"] == "2026-10-31"
    assert manifest.sources["oldp:decisions"] == "408eb916fab64080580e4d67bf4242fb10cdedf5"
    assert set(manifest.sources) == {
        "gii:kschg", "gii:arbzg", "gii:kwg", "gii:bgb", "gii:egbgb", "gii:aktg",
        "eurlex:32016R0679", "eurlex:32003L0088", "oldp:decisions",
    }  # fmt: skip


def test_each_document_is_in_exactly_one_tenant_file(built: tuple[Path, Path, Result]) -> None:
    directory = version_dir(built)
    owner: dict[str, str] = {}
    for tenant in TENANTS:
        for chunk in chunks_of(directory, tenant):
            assert chunk.tenant == tenant
            assert owner.setdefault(str(chunk.doc_id), tenant) == tenant


def test_chunks_land_in_the_tenant_of_their_source(built: tuple[Path, Path, Result]) -> None:
    directory = version_dir(built)
    sources = {t: {c.source for c in chunks_of(directory, t)} for t in TENANTS}
    assert "gii:kschg" in sources["kanzlei_mueller"]
    assert "gii:bgb" in sources["shared_public"]
    assert "gii:kwg" in sources["versicherung_nord"]
    assert sources["stadtwerke_sued"] == {"eurlex:32016R0679"}
    for gii in ("gii:kschg", "gii:bgb", "gii:kwg"):
        assert [t for t in TENANTS if gii in sources[t]] != []
        assert len([t for t in TENANTS if gii in sources[t]]) == 1


def test_the_german_and_english_act_are_twins(built: tuple[Path, Path, Result]) -> None:
    gdpr = chunks_of(version_dir(built), "stadtwerke_sued")
    de = sorted(c.parallel_id for c in gdpr if c.lang is Lang.DE and c.parallel_id)
    en = sorted(c.parallel_id for c in gdpr if c.lang is Lang.EN and c.parallel_id)
    assert de
    assert de == en


def test_two_runs_give_byte_identical_directories(
    built: tuple[Path, Path, Result], tmp_path: Path
) -> None:
    config = built[0]
    assert ingest(config, tmp_path / "again").exit_code == 0
    (again,) = (tmp_path / "again").iterdir()
    first = version_dir(built)
    assert again.name == first.name
    assert {p.name: p.read_bytes() for p in again.iterdir()} == {
        p.name: p.read_bytes() for p in first.iterdir()
    }


def test_rerunning_into_the_same_directory_is_idempotent(
    built: tuple[Path, Path, Result],
) -> None:
    before = {p.name: p.read_bytes() for p in version_dir(built).iterdir()}
    assert ingest(built[0], built[1]).exit_code == 0
    assert {p.name: p.read_bytes() for p in version_dir(built).iterdir()} == before


def test_the_date_defaults_to_today(built: tuple[Path, Path, Result], tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["ingest", "--config", str(built[0]), "--out", str(tmp_path)])
    assert result.exit_code == 0, result.output
    (directory,) = tmp_path.iterdir()
    assert directory.name[:4].isdigit()
    assert directory.name[10] == "."


@pytest.mark.parametrize("date", ["2026-13-01", "11/02/2026", "2026-11-02.abc", "x"])
def test_a_bad_date_is_a_usage_error_and_writes_nothing(
    built: tuple[Path, Path, Result], tmp_path: Path, date: str
) -> None:
    args = ["ingest", "--config", str(built[0]), "--out", str(tmp_path / "o"), "--date", date]
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 2
    assert not (tmp_path / "o").exists()


def test_a_missing_config_is_a_usage_error(tmp_path: Path) -> None:
    result = ingest(tmp_path / "nope.yaml", tmp_path / "o")
    assert result.exit_code == 2
    assert "nope.yaml" in result.output


def test_a_missing_law_is_a_data_error_and_writes_nothing(tmp_path: Path) -> None:
    raw = build_raw_root(tmp_path / "raw", skip=frozenset({"gii:kschg"}))
    result = ingest(fixture_config(tmp_path, raw), tmp_path / "out")
    assert result.exit_code == 3
    assert "kschg" in result.output
    assert not (tmp_path / "out").exists()


def test_a_missing_oldp_dump_is_a_data_error(tmp_path: Path) -> None:
    raw = build_raw_root(tmp_path / "raw", skip=frozenset({"oldp"}))
    result = ingest(fixture_config(tmp_path, raw), tmp_path / "out")
    assert result.exit_code == 3


def test_a_source_without_a_pin_is_refused(tmp_path: Path) -> None:
    raw = build_raw_root(tmp_path / "raw")
    config = fixture_config(tmp_path, raw)
    data = yaml.safe_load(config.read_text("utf-8"))
    data["sources_file"] = str(tmp_path / "sources.yaml")
    (tmp_path / "sources.yaml").write_text("version: 1\nsources: []\n", encoding="utf-8")
    config.write_text(yaml.safe_dump(data), encoding="utf-8")
    result = ingest(config, tmp_path / "out")
    assert result.exit_code == 2
    assert "has no pin" in result.output


def test_the_committed_fixture_plan_is_unchanged_by_the_helper() -> None:
    assert yaml.safe_load(PLAN_FIXTURE.read_text("utf-8"))["plan"]["default_tenant"] is None


# --- the hook for private and injection documents (T2.6, T4.6) ---------------------------------


def extra_doc(doc_id: str, tenant: str, source: str = "synthetic:private") -> Document:
    return Document(
        doc_id=DocId(doc_id), tenant=TenantId(tenant), source=source, lang=Lang.DE,
        title="Vertrag", law_abbrev=None, version_date=None,
        text="Dies ist ein synthetisches Dokument. " * 5, license="synthetic", url=None,
    )  # fmt: skip


def test_the_extra_documents_hook_is_empty_by_default() -> None:
    config = load_model(PLAN_FIXTURE, CorpusBuildConfig)
    assert pipeline_ingest._extra_documents(config) == []


def test_extra_documents_join_their_own_tenant(
    built: tuple[Path, Path, Result], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        pipeline_ingest, "_extra_documents", lambda _cfg: [extra_doc("priv-1", "kanzlei_mueller")]
    )
    assert ingest(built[0], tmp_path).exit_code == 0
    (directory,) = tmp_path.iterdir()
    manifest = verify_corpus(directory)
    assert manifest.sources["synthetic:private"] == "synthetic"
    assert any(c.doc_id == "priv-1" for c in chunks_of(directory, "kanzlei_mueller"))
    assert not any(c.doc_id == "priv-1" for c in chunks_of(directory, "shared_public"))


@pytest.mark.parametrize("doc", [extra_doc("priv-1", "nobody"), extra_doc("priv-2", "unassigned")])
def test_extra_documents_cannot_break_isolation(
    built: tuple[Path, Path, Result],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    doc: Document,
) -> None:
    monkeypatch.setattr(pipeline_ingest, "_extra_documents", lambda _cfg: [doc])
    result = ingest(built[0], tmp_path / "o")
    assert result.exit_code != 0
    assert not (tmp_path / "o").exists()


def test_an_extra_document_reusing_a_public_doc_id_is_refused(
    built: tuple[Path, Path, Result], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    public = chunks_of(version_dir(built), "shared_public")[0]
    clash = extra_doc(str(public.doc_id), "kanzlei_mueller")
    monkeypatch.setattr(pipeline_ingest, "_extra_documents", lambda _cfg: [clash])
    result = ingest(built[0], tmp_path / "o")
    assert result.exit_code == 3
    assert str(public.doc_id) in result.output
    assert not (tmp_path / "o").exists()


def test_the_chunk_limit_stops_the_build(tmp_path: Path) -> None:
    raw = build_raw_root(tmp_path / "raw")
    config = fixture_config(tmp_path, raw)
    data = yaml.safe_load(config.read_text("utf-8"))
    data["max_chunks"] = 5
    config.write_text(yaml.safe_dump(data), encoding="utf-8")
    result = ingest(config, tmp_path / "out")
    assert result.exit_code == 3
    assert "max_chunks" in result.output


def test_manifest_json_is_the_manifest_model(built: tuple[Path, Path, Result]) -> None:
    raw = json.loads((version_dir(built) / "manifest.json").read_text("utf-8"))
    assert CorpusManifest.model_validate(raw).corpus_version == version_dir(built).name
