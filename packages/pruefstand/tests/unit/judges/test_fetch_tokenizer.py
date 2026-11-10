"""``fetch_tokenizer``: download, sha256 check, atomic write (T5.2c)."""

from pathlib import Path

import pytest
import respx
from testsupport.exact_support import char_tokenizer, install_tokenizer
from testsupport.judge_support import MODEL

from pruefstand.core.errors import ConfigError
from pruefstand.judges.exact_tokens import fetch_tokenizer, load_counter, source_url

# --- fetch_tokenizer ----------------------------------------------------------------------------

URL = "https://huggingface.co/acme/judge-x/resolve/abc/tokenizer.json"


def test_fetch_downloads_verifies_and_writes_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = install_tokenizer(tmp_path, monkeypatch, present=False)
    raw = char_tokenizer().to_str().encode("utf-8")
    with respx.mock() as mock:
        route = mock.get(URL).respond(200, content=raw)
        written = fetch_tokenizer(MODEL)
    assert route.called
    assert written == target
    assert target.read_bytes() == raw
    assert not list(target.parent.glob("*.part"))  # the temporary file was renamed
    assert load_counter(MODEL) is not None


def test_fetch_refuses_a_digest_mismatch_and_leaves_no_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = install_tokenizer(tmp_path, monkeypatch, present=False)
    with respx.mock() as mock:
        mock.get(URL).respond(200, content=b"not the pinned tokenizer")
        with pytest.raises(ConfigError, match="differs from the catalogue pin"):
            fetch_tokenizer(MODEL)
    assert not target.exists()
    assert not list(target.parent.glob("*.part"))


def test_fetch_reports_a_failed_download_without_the_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = install_tokenizer(tmp_path, monkeypatch, present=False)
    with respx.mock() as mock:
        mock.get(URL).respond(404, content=b"secret body")
        with pytest.raises(ConfigError, match="cannot download") as raised:
            fetch_tokenizer(MODEL)
    assert "secret body" not in str(raised.value)
    assert not target.exists()


def test_a_bad_source_is_a_config_error() -> None:
    with pytest.raises(ConfigError, match="must look like"):
        source_url("https://example.com/tokenizer.json")
