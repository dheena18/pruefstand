"""``rag-demo index``: options, messages and exit codes (Qdrant and the encoders over respx)."""

import json
import re
from pathlib import Path

import httpx
import pytest
import respx
from rd_support import CONFIGS, FIXTURE_CORPUS, REPO, write_word_tokenizer
from typer.testing import CliRunner

from rag_demo.cli import app

runner = CliRunner()
QDRANT = "http://qdrant.test:6333"


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QDRANT_URL", QDRANT)
    monkeypatch.setenv("EMBED_URL", "http://localhost:8090")
    monkeypatch.setenv("OLLAMA_GPU0_URL", "http://localhost:11434")
    monkeypatch.setenv("RAG_MODEL_CATALOGUE", str(REPO / "infra" / "gpu" / "models.yaml"))
    monkeypatch.delenv("RAG_EMBED_TOKENIZER", raising=False)
    monkeypatch.delenv("QDRANT_API_KEY", raising=False)
    monkeypatch.delenv("PRUEFSTAND_CANDIDATE_API_KEY", raising=False)


def _qdrant(alias_to: str | None = None) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.method == "GET" and request.url.path == "/aliases":
            aliases = [{"alias_name": "chunks_active", "collection_name": alias_to}]
            return httpx.Response(200, json={"result": {"aliases": aliases if alias_to else []}})
        if request.method == "GET":
            return httpx.Response(404, json={})
        return httpx.Response(200, json={"result": True})

    respx.route(host="qdrant.test").mock(side_effect=handler)
    return calls


def _tei() -> None:
    respx.post("http://localhost:8090/embed").mock(
        side_effect=lambda req: httpx.Response(
            200, json=[[0.1] * 384] * len(json.loads(req.content)["inputs"])
        )
    )


def _ollama() -> None:
    respx.post("http://localhost:11434/api/embed").mock(
        side_effect=lambda req: httpx.Response(
            200, json={"embeddings": [[1.0] * 1024] * len(json.loads(req.content)["input"])}
        )
    )


@respx.mock
def test_tei_index_prints_the_chunk_count_and_the_alias_switch() -> None:
    _qdrant()
    _tei()
    result = runner.invoke(
        app,
        [
            "index",
            "--corpus",
            str(FIXTURE_CORPUS),
            "--encoder",
            "tei",
            "--config",
            str(CONFIGS / "rag.yaml"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert result.stdout.startswith("indexed 40 chunks into chunks__fixture-2026-11-03-")
    assert result.stdout.strip().endswith("alias chunks_active switched")


@respx.mock
def test_pr_collection_with_no_alias_says_the_alias_is_unchanged() -> None:
    calls = _qdrant()
    _tei()
    result = runner.invoke(
        app,
        [
            "index",
            "--corpus",
            str(FIXTURE_CORPUS),
            "--collection",
            "pr_7_abc1234",
            "--no-alias",
            "--config",
            str(CONFIGS / "rag.yaml"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "indexed 40 chunks into pr_7_abc1234, alias unchanged" in result.stdout
    assert not any("aliases" in path for _, path in calls)


@respx.mock
def test_ollama_needs_the_tokenizer_file_and_names_the_fetch_command() -> None:
    _qdrant()
    _ollama()
    result = runner.invoke(app, ["index", "--corpus", str(FIXTURE_CORPUS), "--encoder", "ollama"])
    assert result.exit_code == 1
    assert "RAG_EMBED_TOKENIZER" in result.output


@respx.mock
def test_ollama_index_with_the_gpu_config_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tokenizer = write_word_tokenizer(tmp_path / "tokenizer.json")
    monkeypatch.setenv("RAG_EMBED_TOKENIZER", str(tokenizer))
    _qdrant()
    _ollama()
    result = runner.invoke(app, ["index", "--corpus", str(FIXTURE_CORPUS), "--encoder", "ollama"])
    assert result.exit_code == 0, result.output
    assert re.search(r"__bge-m3__b[0-9a-f]{8}, alias chunks_active switched", result.stdout)


def test_encoder_that_disagrees_with_the_config_is_refused() -> None:
    result = runner.invoke(
        app,
        [
            "index",
            "--corpus",
            str(FIXTURE_CORPUS),
            "--encoder",
            "ollama",
            "--config",
            str(CONFIGS / "rag.yaml"),
        ],
    )
    assert result.exit_code == 1
    assert "embed.engine" in result.output


@respx.mock
def test_drop_removes_a_collection() -> None:
    calls = _qdrant(alias_to="chunks__other")
    result = runner.invoke(app, ["index", "--drop", "pr_7_abc1234"])
    assert result.exit_code == 0, result.output
    assert ("DELETE", "/collections/pr_7_abc1234") in calls
    assert "dropped pr_7_abc1234" in result.stdout


@respx.mock
def test_drop_of_the_active_collection_fails() -> None:
    _qdrant(alias_to="chunks__live")
    result = runner.invoke(app, ["index", "--drop", "chunks__live"])
    assert result.exit_code == 1
    assert "active" in result.output


def test_corpus_or_drop_is_required_and_they_exclude_each_other() -> None:
    assert runner.invoke(app, ["index"]).exit_code == 2
    both = runner.invoke(app, ["index", "--corpus", str(FIXTURE_CORPUS), "--drop", "x"])
    assert both.exit_code == 2


def test_a_broken_corpus_is_reported_with_exit_1(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["index", "--corpus", str(tmp_path), "--config", str(CONFIGS / "rag.yaml")]
    )
    assert result.exit_code == 1
    assert "corpus" in result.output
