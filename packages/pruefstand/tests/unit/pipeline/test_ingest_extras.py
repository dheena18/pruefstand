"""The ``_extra_documents`` hook (T2.5): what the build refuses before T2.6 / T4.6 fill it."""

from pathlib import Path

import pytest
import yaml
from testsupport.corpus_support import build_raw_root, fixture_config
from typer.testing import CliRunner, Result

from pruefstand.cli import app
from pruefstand.core.enums import Lang
from pruefstand.core.ids import DocId, TenantId
from pruefstand.core.models.corpus import Document
from pruefstand.pipeline import ingest as pipeline_ingest


def ingest(config: Path, out: Path) -> Result:
    args = ["ingest", "--config", str(config), "--out", str(out), "--date", "2026-11-02"]
    return CliRunner().invoke(app, args)


def extra_doc(tenant: str = "kanzlei_mueller", source: str = "synthetic:private") -> Document:
    return Document(
        doc_id=DocId("priv-1"), tenant=TenantId(tenant), source=source, lang=Lang.DE,
        title="Vertrag", law_abbrev=None, version_date=None,
        text="Dies ist ein synthetisches Dokument. " * 5, license="synthetic", url=None,
    )  # fmt: skip


@pytest.fixture
def config(tmp_path: Path) -> Path:
    return fixture_config(tmp_path, build_raw_root(tmp_path / "raw"))


def use(monkeypatch: pytest.MonkeyPatch, *docs: Document) -> None:
    monkeypatch.setattr(pipeline_ingest, "_extra_documents", lambda _cfg: list(docs))


@pytest.mark.parametrize(
    "source", ["gii:kschg", "gii:unknown", "eurlex:32016R0679", "oldp:decisions", "oldp"]
)
def test_an_extra_document_cannot_claim_a_pinned_source(
    config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: str
) -> None:
    use(monkeypatch, extra_doc(source=source))
    result = ingest(config, tmp_path / "out")
    assert result.exit_code == 2
    assert f"must not claim the pinned source '{source}'" in result.output
    assert not (tmp_path / "out").exists()


def test_an_extra_document_cannot_join_shared_public(
    config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use(monkeypatch, extra_doc(tenant="shared_public"))
    result = ingest(config, tmp_path / "out")
    assert result.exit_code == 2
    assert "shared_public" in result.output
    assert "extra document" in result.output
    assert not (tmp_path / "out").exists()


def test_max_chunks_counts_the_extra_documents(
    config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = ingest(config, tmp_path / "base")
    assert first.exit_code == 0, first.output
    total = sum(int(line.split(": ")[1]) for line in first.stdout.splitlines() if ": " in line)
    data = yaml.safe_load(config.read_text("utf-8"))
    data["max_chunks"] = total
    config.write_text(yaml.safe_dump(data), encoding="utf-8")
    assert ingest(config, tmp_path / "at-limit").exit_code == 0
    use(monkeypatch, extra_doc())
    result = ingest(config, tmp_path / "over")
    assert result.exit_code == 3
    assert "max_chunks" in result.output
    assert not (tmp_path / "over").exists()
