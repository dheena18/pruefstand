"""Tests for scripts/models/fetch.py: SHA-256 check, cleanup on mismatch, idempotence."""

import hashlib
from pathlib import Path

import pytest
import yaml
from models.fetch import FetchError, ModelEntry, fetch_file, load_models, main

PAYLOAD = "Kündigung ".encode() * 100


def _src(tmp_path: Path) -> tuple[str, str]:
    src = tmp_path / "src-abc.bin"
    src.write_bytes(PAYLOAD)
    return src.as_uri(), hashlib.sha256(PAYLOAD).hexdigest()


def test_wrong_sha_fails_and_removes_the_file(tmp_path: Path) -> None:
    url, _ = _src(tmp_path)
    dest = tmp_path / "out" / "m.gguf"
    with pytest.raises(FetchError, match="sha256"):
        fetch_file(url, dest, "0" * 64, allowed_schemes=("file",))
    assert not dest.exists()
    assert not list(dest.parent.glob("*.part"))


def test_correct_sha_downloads_then_is_idempotent(tmp_path: Path) -> None:
    url, sha = _src(tmp_path)
    dest = tmp_path / "out" / "m.gguf"
    assert fetch_file(url, dest, sha, allowed_schemes=("file",)) == "downloaded"
    assert dest.read_bytes() == PAYLOAD
    assert fetch_file((tmp_path / "gone.bin").as_uri(), dest, sha, allowed_schemes=("file",)) == "cached"  # no download


def test_corrupt_existing_file_is_replaced(tmp_path: Path) -> None:
    url, sha = _src(tmp_path)
    dest = tmp_path / "m.gguf"
    dest.write_bytes(b"corrupt")
    assert fetch_file(url, dest, sha, allowed_schemes=("file",)) == "downloaded"
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
    assert main(["--manifest", str(manifest), "--dest", str(tmp_path / "cache"), "--allow-scheme", "file"]) == 0
    assert (tmp_path / "cache" / "t.gguf").read_bytes() == PAYLOAD


def _entry(**over: object) -> dict[str, object]:
    base = {
        "id": "t", "repo": "o/r", "revision": "abc123", "file": "t.gguf",
        "url": "https://huggingface.co/o/r/resolve/abc123/t.gguf",
        "sha256": "0" * 64, "license": "Apache-2.0",
    }  # fmt: skip
    return {**base, **over}


def test_entry_must_be_https_pinned_and_a_plain_file_name() -> None:
    ModelEntry.model_validate(_entry())
    for bad in (
        {"file": "../x.gguf"},
        {"file": "a/b.gguf"},
        {"file": ""},
        {"url": "https://huggingface.co/o/r/resolve/main/t.gguf"},
    ):
        with pytest.raises(ValueError, match=r"file|revision"):
            ModelEntry.model_validate(_entry(**bad))


def test_plain_http_and_other_schemes_are_refused(tmp_path: Path) -> None:
    with pytest.raises(FetchError, match="scheme"):
        fetch_file("http://huggingface.co/x", tmp_path / "m", "0" * 64)
    url, sha = _src(tmp_path)
    with pytest.raises(FetchError, match="scheme"):
        fetch_file(url, tmp_path / "m", sha)  # file:// is refused unless a test allows it


def test_download_is_cut_off_at_size_bytes_plus_one(tmp_path: Path) -> None:
    url, sha = _src(tmp_path)
    dest = tmp_path / "m.gguf"
    with pytest.raises(FetchError, match="size"):
        fetch_file(url, dest, sha, allowed_schemes=("file",), size_bytes=len(PAYLOAD) - 1)
    assert not dest.exists()
    assert not list(tmp_path.glob("*.part"))
    assert fetch_file(url, dest, sha, allowed_schemes=("file",), size_bytes=len(PAYLOAD)) == "downloaded"


def test_a_symlinked_part_file_is_refused(tmp_path: Path) -> None:
    url, sha = _src(tmp_path)
    victim = tmp_path / "victim.txt"
    victim.write_text("keep", encoding="utf-8")
    dest = tmp_path / "m.gguf"
    (tmp_path / "m.gguf.part").symlink_to(victim)
    with pytest.raises(FetchError, match="symlink"):
        fetch_file(url, dest, sha, allowed_schemes=("file",))
    assert victim.read_text(encoding="utf-8") == "keep"
