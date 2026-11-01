import hashlib
import importlib.metadata as md
import os
import pickle
import sqlite3
import stat
from pathlib import Path

import pytest

from pruefstand.core.errors import StoreError
from pruefstand.core.protocols import KVCache
from pruefstand.store.kv import DiskKVCache


def test_set_then_get_returns_the_bytes(tmp_path: Path) -> None:
    with DiskKVCache(tmp_path, "target") as cache:
        cache.set("k", b"v")
        assert cache.get("k") == b"v"


def test_german_bytes_survive(tmp_path: Path) -> None:
    value = "Kündigungsschutzgesetz".encode()
    with DiskKVCache(tmp_path, "llm") as cache:
        cache.set("k", value)
        assert cache.get("k") == value


def test_missing_key_is_none(tmp_path: Path) -> None:
    with DiskKVCache(tmp_path, "target") as cache:
        assert cache.get("missing") is None


def test_namespaces_in_one_directory_are_isolated(tmp_path: Path) -> None:
    with DiskKVCache(tmp_path, "target") as target, DiskKVCache(tmp_path, "llm") as llm:
        target.set("k", b"target-value")
        assert llm.get("k") is None
        llm.set("k", b"llm-value")
        assert target.get("k") == b"target-value"


def test_value_persists_across_instances(tmp_path: Path) -> None:
    with DiskKVCache(tmp_path, "target") as first:
        first.set("k", b"v")
    with DiskKVCache(tmp_path, "target") as second:
        assert second.get("k") == b"v"


def test_read_only_reads_but_does_not_write(tmp_path: Path) -> None:
    with DiskKVCache(tmp_path, "target") as writer:
        writer.set("k", b"v")
    with DiskKVCache(tmp_path, "target", read_only=True) as reader:
        assert reader.get("k") == b"v"
        with pytest.raises(StoreError):
            reader.set("k2", b"x")
        assert reader.get("k2") is None


def test_read_only_on_a_missing_directory_is_empty_and_creates_nothing(tmp_path: Path) -> None:
    target = tmp_path / "does-not-exist"
    with DiskKVCache(target, "target", read_only=True) as reader:
        assert reader.get("k") is None
        with pytest.raises(StoreError):
            reader.set("k", b"v")
    assert not target.exists()


def test_it_satisfies_the_kvcache_protocol(tmp_path: Path) -> None:
    with DiskKVCache(tmp_path, "target") as cache:
        assert isinstance(cache, KVCache)


def test_use_after_close_is_a_store_error(tmp_path: Path) -> None:
    cache = DiskKVCache(tmp_path, "target")
    cache.close()
    cache.close()  # idempotent
    with pytest.raises(StoreError):
        cache.get("k")


def test_store_is_plain_sqlite_with_bytes_values_and_no_pickle(tmp_path: Path) -> None:
    with DiskKVCache(tmp_path, "target") as cache:
        cache.set("k", b"\x80\x04pickle-looking bytes stay bytes")
    files = list((tmp_path / "target").iterdir())
    assert [f.name for f in files] == ["cache.sqlite3"]
    row = sqlite3.connect(files[0]).execute("select key, value from kv").fetchone()
    assert row == ("k", b"\x80\x04pickle-looking bytes stay bytes")


def test_a_corrupt_cache_file_is_a_store_error(tmp_path: Path) -> None:
    (tmp_path / "target").mkdir()
    (tmp_path / "target" / "cache.sqlite3").write_bytes(b"this is not a database" * 100)
    with pytest.raises(StoreError), DiskKVCache(tmp_path, "target") as cache:
        cache.get("k")


def test_overwriting_a_key_keeps_the_last_value(tmp_path: Path) -> None:
    with DiskKVCache(tmp_path, "llm") as cache:
        cache.set("k", b"1")
        cache.set("k", b"2")
        assert cache.get("k") == b"2"


def test_the_package_no_longer_depends_on_diskcache() -> None:
    deps = md.requires("pruefstand") or []
    assert not [d for d in deps if d.lower().startswith("diskcache")]


class _Evil:
    """Unpickling this creates ``marker`` (stands in for code execution)."""

    def __init__(self, marker: Path) -> None:
        self.marker = marker

    def __reduce__(self) -> tuple[object, tuple[str, str]]:
        return (open, (str(self.marker), "w"))


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_a_planted_pickle_blob_is_returned_as_bytes_and_never_executed(tmp_path: Path) -> None:
    marker = tmp_path / "pwned"
    blob = pickle.dumps(_Evil(marker))
    with DiskKVCache(tmp_path, "target") as cache:
        cache.set("other", b"x")
    db = sqlite3.connect(tmp_path / "target" / "cache.sqlite3")
    db.execute("INSERT INTO kv (key, value) VALUES (?, ?)", ("planted", blob))
    db.commit()
    db.close()
    with DiskKVCache(tmp_path, "target") as cache:
        assert cache.get("planted") == blob
    assert not marker.exists()


def test_read_only_get_leaves_every_byte_of_the_cache_directory_alone(tmp_path: Path) -> None:
    with DiskKVCache(tmp_path, "target") as writer:
        writer.set("k", b"v")
    folder = tmp_path / "target"
    before = ({p.name: _digest(p) for p in folder.iterdir()}, {p.name: p.stat().st_mtime_ns for p in folder.iterdir()})
    with DiskKVCache(tmp_path, "target", read_only=True) as reader:
        assert reader.get("k") == b"v"
        assert reader.get("missing") is None
    after = ({p.name: _digest(p) for p in folder.iterdir()}, {p.name: p.stat().st_mtime_ns for p in folder.iterdir()})
    assert after == before


def test_read_only_works_on_a_read_only_directory(tmp_path: Path) -> None:
    with DiskKVCache(tmp_path, "target") as writer:
        writer.set("k", b"v")
    folder = tmp_path / "target"
    os.chmod(folder / "cache.sqlite3", stat.S_IRUSR)
    os.chmod(folder, stat.S_IRUSR | stat.S_IXUSR)
    try:
        with DiskKVCache(tmp_path, "target", read_only=True) as reader:
            assert reader.get("k") == b"v"
    finally:
        os.chmod(folder, stat.S_IRWXU)
