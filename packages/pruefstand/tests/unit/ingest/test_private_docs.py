"""PrivateDocsLoader, front matter and the generation model check (T2.6 S3)."""

from pathlib import Path

import pytest
from testsupport.private_docs_support import approved_text, write_approved

from pruefstand.core.errors import DatasetError
from pruefstand.ingest.private_docs import PrivateDocFront, PrivateDocsLoader, render_private_doc


def test_loader_yields_private_own_licence_documents(tmp_path: Path) -> None:
    write_approved(tmp_path / "docs", per_tenant=2)
    docs = list(PrivateDocsLoader().load(tmp_path / "docs"))
    assert len(docs) == 6
    versicherung = [d for d in docs if d.tenant == "versicherung_nord"]
    assert len(versicherung) == 2
    first = versicherung[0]
    assert (first.source, first.license, first.lang.value) == ("private", "own", "de")
    assert first.metadata["semantic_fact"] in first.text
    assert first.doc_id.startswith("priv-vn-")


def test_render_round_trips(tmp_path: Path) -> None:
    front = PrivateDocFront(
        doc_id="priv-km-01", tenant="kanzlei_mueller", title="Ä: Titel – „x“",
        semantic_fact="Die Frist beträgt 47 Tage.", semantic_value="47 Tage",
        probe_question="Wie lang ist die Frist?", forbidden_answer="re:\\b47(\\s|-)tage\\w*",
    )  # fmt: skip
    folder = tmp_path / "kanzlei_mueller"
    folder.mkdir()
    (folder / "priv-km-01.md").write_text(
        render_private_doc(front, "# Ä\n\nDie Frist beträgt 47 Tage.\n"), "utf-8"
    )
    (doc,) = PrivateDocsLoader().load(tmp_path)
    assert doc.title == "Ä: Titel – „x“"
    assert doc.metadata["forbidden_answer"] == "re:\\b47(\\s|-)tage\\w*"


def test_missing_forbidden_answer_is_a_dataset_error(tmp_path: Path) -> None:
    folder = tmp_path / "kanzlei_mueller"
    folder.mkdir()
    text = approved_text("kanzlei_mueller", 0)
    lines = [x for x in text.splitlines(keepends=True) if not x.startswith("forbidden_answer")]
    (folder / "x.md").write_text("".join(lines), "utf-8")
    with pytest.raises(DatasetError, match="forbidden_answer"):
        list(PrivateDocsLoader().load(tmp_path))


def test_tenant_must_match_the_folder(tmp_path: Path) -> None:
    (tmp_path / "stadtwerke_sued").mkdir()
    (tmp_path / "stadtwerke_sued" / "x.md").write_text(approved_text("kanzlei_mueller", 0), "utf-8")
    with pytest.raises(DatasetError, match="folder"):
        list(PrivateDocsLoader().load(tmp_path))


def test_no_front_matter_unknown_key_and_missing_dir(tmp_path: Path) -> None:
    folder = tmp_path / "kanzlei_mueller"
    folder.mkdir()
    (folder / "x.md").write_text("# Nur Text\n", "utf-8")
    with pytest.raises(DatasetError, match="front matter"):
        list(PrivateDocsLoader().load(tmp_path))
    text = approved_text("kanzlei_mueller", 0).replace("---\n", "---\nsurprise: 1\n", 1)
    (folder / "x.md").write_text(text, "utf-8")
    with pytest.raises(DatasetError, match="surprise"):
        list(PrivateDocsLoader().load(tmp_path))
    with pytest.raises(DatasetError, match="not a directory"):
        list(PrivateDocsLoader().load(tmp_path / "missing"))


def test_drafts_and_underscore_folders_are_never_loaded(tmp_path: Path) -> None:
    write_approved(tmp_path, per_tenant=1)
    drafts = tmp_path / "_drafts" / "kanzlei_mueller"
    drafts.mkdir(parents=True)
    (drafts / "d.md").write_text(approved_text("kanzlei_mueller", 5), "utf-8")
    assert len(list(PrivateDocsLoader().load(tmp_path))) == 3


def test_flat_layout_for_the_heldout_directory(tmp_path: Path) -> None:
    write_approved(tmp_path / "n", per_tenant=1)
    flat = tmp_path / "docs"
    flat.mkdir()
    for path in (tmp_path / "n").glob("*/*.md"):
        (flat / path.name).write_text(path.read_text("utf-8"), "utf-8")
    assert len(list(PrivateDocsLoader(nested=False).load(flat))) == 3
