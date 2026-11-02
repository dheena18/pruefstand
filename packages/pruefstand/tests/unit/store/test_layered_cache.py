"""``LayeredKVCache`` and ``build_cache``: the cache trust domains (T6.1 S2)."""

from pathlib import Path

import pytest

from pruefstand.core.errors import StoreError
from pruefstand.core.protocols import KVCache
from pruefstand.store.kv import DiskKVCache, LayeredKVCache, build_cache


def seeded(directory: Path, **entries: bytes) -> None:
    with DiskKVCache(directory, "target") as cache:
        for key, value in entries.items():
            cache.set(key, value)


def snapshot(directory: Path) -> bytes:
    return (directory / "target" / "cache.sqlite3").read_bytes()


def test_a_read_hits_the_base(tmp_path: Path) -> None:
    seeded(tmp_path / "base", k=b"base")
    with (
        DiskKVCache(tmp_path / "base", "target", read_only=True) as base,
        DiskKVCache(tmp_path / "overlay", "target") as overlay,
    ):
        assert LayeredKVCache(base, overlay).get("k") == b"base"


def test_a_write_goes_to_the_overlay_and_leaves_the_base_byte_for_byte(tmp_path: Path) -> None:
    seeded(tmp_path / "base", k=b"base")
    before = snapshot(tmp_path / "base")
    with (
        DiskKVCache(tmp_path / "base", "target", read_only=True) as base,
        DiskKVCache(tmp_path / "overlay", "target") as overlay,
    ):
        layered = LayeredKVCache(base, overlay)
        layered.set("new", b"value")
        assert layered.get("new") == b"value"
        assert overlay.get("new") == b"value"
        assert base.get("new") is None
    assert snapshot(tmp_path / "base") == before


def test_the_overlay_shadows_the_base(tmp_path: Path) -> None:
    seeded(tmp_path / "base", k=b"old")
    with (
        DiskKVCache(tmp_path / "base", "target", read_only=True) as base,
        DiskKVCache(tmp_path / "overlay", "target") as overlay,
    ):
        layered = LayeredKVCache(base, overlay)
        layered.set("k", b"new")
        assert layered.get("k") == b"new"
        assert base.get("k") == b"old"


def test_a_missing_key_is_a_miss(tmp_path: Path) -> None:
    with (
        DiskKVCache(tmp_path / "base", "target", read_only=True) as base,
        DiskKVCache(tmp_path / "overlay", "target") as overlay,
    ):
        assert LayeredKVCache(base, overlay).get("nope") is None


def test_a_base_opened_read_only_raises_on_a_direct_write(tmp_path: Path) -> None:
    seeded(tmp_path / "base", k=b"base")
    with (
        DiskKVCache(tmp_path / "base", "target", read_only=True) as base,
        pytest.raises(StoreError, match="read-only"),
    ):
        base.set("x", b"y")


def test_both_layers_satisfy_the_kv_protocol(tmp_path: Path) -> None:
    layered = build_cache("overlay", tmp_path / "shared", tmp_path / "overlay")
    assert isinstance(layered, KVCache)
    layered.close()


def test_overlay_mode_never_writes_the_shared_cache(tmp_path: Path) -> None:
    seeded(tmp_path / "shared", k=b"shared")
    before = snapshot(tmp_path / "shared")
    with build_cache("overlay", tmp_path / "shared", tmp_path / "overlay") as cache:
        assert cache.get("k") == b"shared"
        cache.set("pr-only", b"1")
    assert snapshot(tmp_path / "shared") == before
    with DiskKVCache(tmp_path / "overlay", "target", read_only=True) as overlay:
        assert overlay.get("pr-only") == b"1"


def test_overlay_mode_with_no_shared_cache_yet_is_an_empty_base(tmp_path: Path) -> None:
    with build_cache("overlay", tmp_path / "missing", tmp_path / "overlay") as cache:
        assert cache.get("k") is None
        cache.set("k", b"v")
        assert cache.get("k") == b"v"
    assert not (tmp_path / "missing").exists()


def test_shared_mode_writes_the_shared_cache(tmp_path: Path) -> None:
    with build_cache("shared", tmp_path / "shared", tmp_path / "overlay") as cache:
        cache.set("k", b"v")
    assert not (tmp_path / "overlay").exists()
    with DiskKVCache(tmp_path / "shared", "target", read_only=True) as shared:
        assert shared.get("k") == b"v"


def test_the_llm_namespace_is_separate(tmp_path: Path) -> None:
    with build_cache("shared", tmp_path / "s", tmp_path / "o", namespace="llm") as llm:
        llm.set("k", b"llm")
    with build_cache("shared", tmp_path / "s", tmp_path / "o") as target:
        assert target.get("k") is None


def test_an_unknown_mode_is_refused(tmp_path: Path) -> None:
    with pytest.raises(StoreError, match="cache mode"):
        build_cache("both", tmp_path / "s", tmp_path / "o")


def test_closing_twice_is_fine(tmp_path: Path) -> None:
    cache = build_cache("overlay", tmp_path / "s", tmp_path / "o")
    cache.close()
    cache.close()
