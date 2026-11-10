"""scripts/validate_corpus.py (T2.5): a corpus directory against schemas/chunk.schema.json."""

import json
from pathlib import Path

import pytest
from testsupport.corpus_support import build_raw_root, fixture_config
from typer.testing import CliRunner
from validate_corpus import main

from pruefstand.cli import app


@pytest.fixture(scope="module")
def corpus(tmp_path_factory: pytest.TempPathFactory) -> Path:
    base = tmp_path_factory.mktemp("validate")
    config = fixture_config(base, build_raw_root(base / "raw"))
    result = CliRunner().invoke(
        app, ["ingest", "--config", str(config), "--out", str(base / "out"), "--date", "2026-11-02"]
    )
    assert result.exit_code == 0, result.output
    (directory,) = (base / "out").iterdir()
    return directory


def test_a_good_corpus_prints_ok_and_the_chunk_count(
    corpus: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([str(corpus)]) == 0
    manifest = json.loads((corpus / "manifest.json").read_text("utf-8"))
    assert capsys.readouterr().out.strip() == f"OK n={sum(manifest['tenants'].values())}"


def copy_corpus(corpus: Path, tmp_path: Path) -> Path:
    target = tmp_path / corpus.name
    target.mkdir()
    for path in corpus.iterdir():
        (target / path.name).write_bytes(path.read_bytes())
    return target


def test_a_line_that_breaks_the_schema_is_reported_with_file_and_line(
    corpus: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    broken = copy_corpus(corpus, tmp_path)
    path = broken / "shared_public.chunks.jsonl"
    lines = path.read_text("utf-8").splitlines()
    record = json.loads(lines[1])
    record["surprise"] = 1
    lines[1] = json.dumps(record, sort_keys=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert main([str(broken)]) == 1
    assert "shared_public.chunks.jsonl:2" in capsys.readouterr().err


def test_a_changed_file_fails_the_hash_check(
    corpus: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    broken = copy_corpus(corpus, tmp_path)
    path = broken / "kanzlei_mueller.chunks.jsonl"
    path.write_bytes(path.read_bytes() + b"\n")
    assert main([str(broken)]) == 1
    assert "sha256" in capsys.readouterr().err


def test_a_missing_directory_is_a_usage_error(tmp_path: Path) -> None:
    assert main([str(tmp_path / "nope")]) == 2


def test_a_corpus_agrees_with_the_plan_it_was_built_with(
    corpus: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plan = corpus.parent.parent / "corpus.yaml"
    assert main([str(corpus), "--plan", str(plan)]) == 0
    assert capsys.readouterr().out.startswith("OK n=")


def test_a_plan_that_does_not_declare_the_tenants_fails(
    corpus: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plan = tmp_path / "corpus.yaml"
    plan.write_text("plan: {tenants: [other], default_tenant: other}\n", encoding="utf-8")
    assert main([str(corpus), "--plan", str(plan)]) == 1
    assert "not declared by the plan" in capsys.readouterr().err


def test_an_unreadable_plan_is_an_error_not_a_traceback(
    corpus: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([str(corpus), "--plan", str(tmp_path / "missing.yaml")]) == 1
    assert capsys.readouterr().err.startswith("error: ")


def test_the_committed_slice_fixture_fails_by_design(
    capsys: pytest.CaptureFixture[str],
) -> None:
    slice_dir = Path(__file__).resolve().parents[2] / "corpus" / "slice_v1"
    assert main([str(slice_dir)]) == 1  # documented in the module docstring of validate_corpus
    assert "corpus_version" in capsys.readouterr().err
