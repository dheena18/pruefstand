"""``target_cache``: the shared cache for main/nightly, a per-job overlay for PRs (T6.1 S3)."""

from pathlib import Path

import pytest

from pruefstand.core.errors import ConfigError
from pruefstand.core.models.target import TargetInfo
from pruefstand.pipeline.cache import (
    cache_mode,
    identity_is_opaque,
    target_cache,
    trusted_target_id,
)
from pruefstand.store.kv import DiskKVCache, LayeredKVCache


def env_of(tmp_path: Path, mode: str | None = None) -> dict[str, str]:
    env = {
        "PRUEFSTAND_CACHE_DIR": str(tmp_path / "shared"),
        "PRUEFSTAND_HOME": str(tmp_path / "home"),
    }
    if mode is not None:
        env["PRUEFSTAND_CACHE_MODE"] = mode
    return env


def failing_job(env: dict[str, str]) -> None:
    with target_cache(env):
        msg = "job failed"
        raise RuntimeError(msg)


def seed(tmp_path: Path) -> None:
    with DiskKVCache(tmp_path / "shared", "target") as cache:
        cache.set("k", b"main")


def test_the_default_mode_is_overlay() -> None:
    assert cache_mode({}) == "overlay"
    assert cache_mode({"PRUEFSTAND_CACHE_MODE": ""}) == "overlay"


@pytest.mark.parametrize("mode", ["shared", "overlay"])
def test_both_modes_are_accepted(mode: str) -> None:
    assert cache_mode({"PRUEFSTAND_CACHE_MODE": mode}) == mode


@pytest.mark.parametrize("mode", ["SHARED", "both", "off", "../x", "1"])
def test_another_mode_is_a_config_error_that_names_the_choices(mode: str) -> None:
    with pytest.raises(ConfigError, match="shared"):
        cache_mode({"PRUEFSTAND_CACHE_MODE": mode})


def test_overlay_reads_main_writes_a_temp_dir_and_deletes_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed(tmp_path)
    before = (tmp_path / "shared" / "target" / "cache.sqlite3").read_bytes()
    temp = tmp_path / "tmp"
    temp.mkdir()
    monkeypatch.setattr("tempfile.tempdir", str(temp))
    with target_cache(env_of(tmp_path)) as cache:
        assert isinstance(cache, LayeredKVCache)
        assert cache.get("k") == b"main"
        cache.set("pr", b"1")
        assert list(temp.iterdir())  # the overlay lives in a per-job temporary directory
    assert list(temp.iterdir()) == []
    assert (tmp_path / "shared" / "target" / "cache.sqlite3").read_bytes() == before


def test_the_overlay_is_deleted_even_when_the_job_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    temp = tmp_path / "tmp"
    temp.mkdir()
    monkeypatch.setattr("tempfile.tempdir", str(temp))
    with pytest.raises(RuntimeError):
        failing_job(env_of(tmp_path))
    assert list(temp.iterdir()) == []


def test_shared_mode_writes_the_shared_cache(tmp_path: Path) -> None:
    with target_cache(env_of(tmp_path, "shared")) as cache:
        assert isinstance(cache, DiskKVCache)
        cache.set("k", b"v")
    with DiskKVCache(tmp_path / "shared", "target", read_only=True) as shared:
        assert shared.get("k") == b"v"


def test_the_cache_dir_defaults_to_the_pruefstand_home(tmp_path: Path) -> None:
    env = {"PRUEFSTAND_HOME": str(tmp_path / "home"), "PRUEFSTAND_CACHE_MODE": "shared"}
    with target_cache(env) as cache:
        assert cache is not None
        cache.set("k", b"v")
    assert (tmp_path / "home" / "cache" / "target" / "cache.sqlite3").is_file()


def test_an_unusable_cache_directory_means_no_cache_not_a_failed_run(tmp_path: Path) -> None:
    blocker = tmp_path / "shared"
    blocker.write_text("a file where the cache directory should be", encoding="utf-8")
    with target_cache(env_of(tmp_path, "shared")) as cache:
        assert cache is None


def test_an_unreadable_shared_cache_in_overlay_mode_still_gives_a_working_overlay(
    tmp_path: Path,
) -> None:
    shared = tmp_path / "shared" / "target"
    shared.mkdir(parents=True)
    (shared / "cache.sqlite3").write_bytes(b"not a database" * 100)
    with target_cache(env_of(tmp_path)) as cache:
        assert cache is not None
        cache.set("k", b"v")
        assert cache.get("k") == b"v"


def test_the_trusted_target_id_is_optional_and_validated() -> None:
    assert trusted_target_id({}) is None
    assert trusted_target_id({"PRUEFSTAND_TRUSTED_TARGET_ID": "sha256:" + "a" * 64}) is not None
    for bad in ("bad id", "x;y", "-x", "a" * 201):
        with pytest.raises(ConfigError, match="TRUSTED_TARGET_ID"):
            trusted_target_id({"PRUEFSTAND_TRUSTED_TARGET_ID": bad})


@pytest.mark.parametrize(
    ("git_sha", "digest", "opaque"),
    [
        ("unknown", None, True),
        ("", None, True),
        ("unknown", "sha256:" + "a" * 64, False),
        ("abc123", None, False),
    ],
)
def test_an_identity_without_sha_and_digest_is_opaque(
    git_sha: str, digest: str | None, opaque: bool
) -> None:
    info = TargetInfo(
        app_version="1",
        git_sha=git_sha,
        image_digest=digest,
        config_hash="c",
        corpus_version="v",
        models={},
    )
    assert identity_is_opaque(info) is opaque
    assert identity_is_opaque(None) is True


def test_a_disabled_cache_is_none_and_touches_nothing(tmp_path: Path) -> None:
    with target_cache(env_of(tmp_path, "shared"), enabled=False) as cache:
        assert cache is None
    assert not (tmp_path / "shared").exists()


def test_without_use_base_main_s_cache_is_not_read(tmp_path: Path) -> None:
    seed(tmp_path)
    with target_cache(env_of(tmp_path), use_base=False) as cache:
        assert cache is not None
        assert cache.get("k") is None
        cache.set("pr", b"1")
        assert cache.get("pr") == b"1"
