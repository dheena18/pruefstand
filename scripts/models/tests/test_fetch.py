"""Tests for scripts/models/fetch.py: SHA-256 check, cleanup on mismatch, idempotence."""

import hashlib
from pathlib import Path

import pytest
import yaml
from models.fetch import FetchError, fetch_file, load_models, main

PAYLOAD = "Kündigung ".encode() * 100


def _src(tmp_path: Path) -> tuple[str, str]:
    src = tmp_path / "src.bin"
    src.write_bytes(PAYLOAD)
    return src.as_uri(), hashlib.sha256(PAYLOAD).hexdigest()


def test_wrong_sha_fails_and_removes_the_file(tmp_path: Path) -> None:
    url, _ = _src(tmp_path)
    dest = tmp_path / "out" / "m.gguf"
    with pytest.raises(FetchError, match="sha256"):
        fetch_file(url, dest, "0" * 64)
    assert not dest.exists()
    assert not list(dest.parent.glob("*.part"))


def test_correct_sha_downloads_then_is_idempotent(tmp_path: Path) -> None:
    url, sha = _src(tmp_path)
    dest = tmp_path / "out" / "m.gguf"
    assert fetch_file(url, dest, sha) == "downloaded"
    assert dest.read_bytes() == PAYLOAD
    assert fetch_file((tmp_path / "gone.bin").as_uri(), dest, sha) == "cached"  # no download


def test_corrupt_existing_file_is_replaced(tmp_path: Path) -> None:
    url, sha = _src(tmp_path)
    dest = tmp_path / "m.gguf"
    dest.write_bytes(b"corrupt")
    assert fetch_file(url, dest, sha) == "downloaded"
    assert dest.read_bytes() == PAYLOAD


def test_the_committed_manifest_is_complete() -> None:
    models = load_models(Path("infra/models/test-models.yaml"))
    assert models
    for entry in models:
        assert len(entry.sha256) == 64
        assert entry.url.startswith("https://huggingface.co/")
        assert entry.revision in entry.url
        assert entry.license


def test_main_fetches_listed_models(tmp_path: Path) -> None:
    url, sha = _src(tmp_path)
    manifest = tmp_path / "models.yaml"
    manifest.write_text(
        yaml.safe_dump(
            {
                "models": [
                    {
                        "id": "t",
                        "repo": "o/r",
                        "revision": "abc",
                        "file": "t.gguf",
                        "url": url,
                        "sha256": sha,
                        "license": "Apache-2.0",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    assert main(["--manifest", str(manifest), "--dest", str(tmp_path / "cache")]) == 0
    assert (tmp_path / "cache" / "t.gguf").read_bytes() == PAYLOAD
