"""Tokenizer fetch (build-time bake of the embedding tokenizer, DEV11-21) and encoder wiring."""

import hashlib
from pathlib import Path

import httpx
import pytest
import respx
from rd_support import CONFIGS, REPO, write_word_tokenizer

from rag_demo.catalogue import load_catalogue
from rag_demo.config import Settings, load_config
from rag_demo.errors import ConfigError
from rag_demo.index.encoders import OllamaDenseEncoder, TeiDenseEncoder
from rag_demo.index.fetch_tokenizer import fetch, main, source_url, verify
from rag_demo.index.tokens import load_token_counter
from rag_demo.wiring import build_dense, build_retriever, catalogue_options

CATALOGUE = REPO / "infra" / "gpu" / "models.yaml"
REV = "5617a9f61b028005a4858fdac845db406aefb181"
SOURCE = f"hf:BAAI/bge-m3@{REV}/tokenizer.json"
BGE_URL = f"https://huggingface.co/BAAI/bge-m3/resolve/{REV}/tokenizer.json"


def test_source_url_maps_hf_sources_and_rejects_others() -> None:
    assert source_url(SOURCE) == BGE_URL  # pinned to a commit
    assert source_url("hf:BAAI/bge-m3/tokenizer.json").endswith("/resolve/main/tokenizer.json")
    with pytest.raises(ConfigError, match="hf:"):
        source_url("https://example.org/tokenizer.json")


def test_verify_accepts_the_pinned_digest_and_names_a_mismatch() -> None:
    verify(b"abc", hashlib.sha256(b"abc").hexdigest())
    with pytest.raises(ConfigError, match="differs from the catalogue pin"):
        verify(b"abd", hashlib.sha256(b"abc").hexdigest())


def test_the_catalogue_pins_the_bge_m3_tokenizer() -> None:
    entry = load_catalogue(CATALOGUE)["ollama/bge-m3"]
    assert entry.tokenizer is not None
    assert entry.tokenizer.source == SOURCE
    assert len(entry.tokenizer.sha256) == 64


@respx.mock
def test_fetch_downloads_verifies_and_writes_atomically(tmp_path: Path) -> None:
    body = write_word_tokenizer(tmp_path / "src.json").read_bytes()
    catalogue = tmp_path / "models.yaml"
    sha = hashlib.sha256(body).hexdigest()
    catalogue.write_text(
        "models:\n  - {id: ollama/bge-m3, engine: ollama, tag: bge-m3, family: bge, role: embed,\n"
        f"     tokenizer: {{source: '{SOURCE}', sha256: {sha}}}}}\n",
        encoding="utf-8",
    )
    respx.get(BGE_URL).mock(return_value=httpx.Response(200, content=body))
    out = fetch(catalogue, "ollama/bge-m3", tmp_path / "out" / "bge-m3.json")
    assert out.read_bytes() == body
    assert not list((tmp_path / "out").glob("*.part"))
    assert load_token_counter(out)("a b") == 2


@respx.mock
def test_fetch_refuses_a_wrong_digest_and_an_unpinned_entry(tmp_path: Path) -> None:
    respx.get(BGE_URL).mock(return_value=httpx.Response(200, content=b"{}"))
    with pytest.raises(ConfigError, match="differs"):
        fetch(CATALOGUE, "ollama/bge-m3", tmp_path / "t.json")
    assert not (tmp_path / "t.json").exists()
    with pytest.raises(ConfigError, match="no tokenizer pin"):
        fetch(CATALOGUE, "ollama/gemma3:12b-missing", tmp_path / "t.json")


@respx.mock
def test_fetch_download_error_is_a_config_error(tmp_path: Path) -> None:
    respx.get(BGE_URL).mock(return_value=httpx.Response(503))
    with pytest.raises(ConfigError, match="cannot download"):
        fetch(CATALOGUE, "ollama/bge-m3", tmp_path / "t.json")


@respx.mock
def test_main_needs_catalogue_and_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("RAG_MODEL_CATALOGUE", raising=False)
    monkeypatch.delenv("RAG_EMBED_TOKENIZER", raising=False)
    with pytest.raises(SystemExit):
        main([])
    body = b"x"
    respx.get(BGE_URL).mock(return_value=httpx.Response(200, content=body))
    monkeypatch.setattr("rag_demo.index.fetch_tokenizer.verify", lambda *_: None)
    out = tmp_path / "tok.json"
    assert main(["--catalogue", str(CATALOGUE), "--out", str(out)]) == 0
    assert str(out) in capsys.readouterr().out


# --- wiring of the encoders -------------------------------------------------------------------


def test_gpu_config_builds_the_ollama_encoder_with_catalogue_options() -> None:
    cfg = load_config(CONFIGS / "rag.gpu.yaml", CATALOGUE)
    catalogue = load_catalogue(CATALOGUE)
    options = catalogue_options(cfg, catalogue)
    assert options == {
        "num_ctx": 1024,
        "num_predict": 1,
        "temperature": 0.0,
        "seed": 0,
        "top_p": 1.0,
    }
    assert isinstance(options["num_ctx"], int)
    encoder = build_dense(cfg, "http://localhost:11434", catalogue=catalogue)
    assert isinstance(encoder, OllamaDenseEncoder)


def test_live_config_builds_the_tei_encoder(tmp_path: Path) -> None:
    cfg = load_config(CONFIGS / "rag.yaml")
    assert catalogue_options(cfg, None) is None
    assert isinstance(build_dense(cfg, "http://localhost:8090"), TeiDenseEncoder)


def test_a_configured_tokenizer_is_loaded_and_a_bad_one_fails_at_start(tmp_path: Path) -> None:
    cfg = load_config(CONFIGS / "rag.gpu.yaml", CATALOGUE)
    tokenizer = write_word_tokenizer(tmp_path / "tok.json")
    build_dense(cfg, "http://localhost:11434", tokenizer=tokenizer)
    with pytest.raises(ConfigError, match="tokenizer"):
        build_dense(cfg, "http://localhost:11434", tokenizer=tmp_path / "missing.json")


def test_retriever_gets_the_real_encoder_for_tier_2(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RERANK_URL", "http://rerank-cpu:8201")
    cfg = load_config(CONFIGS / "rag.gpu.yaml", CATALOGUE)
    settings = Settings(rag_model_catalogue=CATALOGUE)
    retriever = build_retriever(cfg, settings, "http://localhost:11434", load_catalogue(CATALOGUE))
    assert isinstance(retriever._dense, OllamaDenseEncoder)
