"""``pruefstand run`` with the target cache: shared for main, overlay for PRs (T6.1 S3, D446).

The cache key rests on the target's identity. A PR candidate is untrusted code, so it never reads
main's cache unless the executor vouches for its identity (``PRUEFSTAND_TRUSTED_TARGET_ID``), and a
target that reports no usable identity gets no cache at all.
"""

import tempfile
from pathlib import Path

import pytest
import respx
from testsupport.cli_support import do_run, manifest_of
from testsupport.pipeline_support import GOOD_URL
from testsupport.target_cassette import TargetCassette
from typer.testing import CliRunner

TRUSTED = "sha256:" + "a" * 64


def shared_db(tmp_path: Path) -> Path:
    return tmp_path / "cache" / "target" / "cache.sqlite3"


@pytest.fixture(autouse=True)
def _cache_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PRUEFSTAND_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.delenv("PRUEFSTAND_CACHE_MODE", raising=False)
    monkeypatch.delenv("PRUEFSTAND_TRUSTED_TARGET_ID", raising=False)


@pytest.fixture
def good(router: respx.MockRouter) -> TargetCassette:
    """A target that reports a usable identity (a git sha)."""
    cassette = TargetCassette("good", info_overrides={"git_sha": "abc123"})
    cassette.install(router, GOOD_URL)
    return cassette


@pytest.fixture
def opaque(router: respx.MockRouter) -> TargetCassette:
    """The recorded rag-demo as built without build arguments: git sha ``unknown``, no digest."""
    cassette = TargetCassette("good")
    cassette.install(router, GOOD_URL)
    return cassette


def shared_run(cli: CliRunner, config: Path, tmp_path: Path, mp: pytest.MonkeyPatch) -> dict:  # type: ignore[type-arg]  # run.json
    mp.setenv("PRUEFSTAND_CACHE_MODE", "shared")
    return manifest_of(do_run(cli, config, tmp_path / "runs"))


def test_a_second_shared_run_is_answered_entirely_from_the_cache(
    cli: CliRunner,
    good: TargetCassette,
    good_config: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = shared_run(cli, good_config, tmp_path, monkeypatch)
    second = shared_run(cli, good_config, tmp_path, monkeypatch)
    assert first["counts"].get("cached", 0) == 0
    assert second["counts"]["cached"] == second["n_cases"]
    assert "cached_from_base" not in second["counts"]  # main reads its own cache
    assert second["target_fingerprint"] == first["target_fingerprint"]


def test_the_default_overlay_mode_never_writes_the_shared_cache(
    cli: CliRunner, good: TargetCassette, good_config: Path, tmp_path: Path
) -> None:
    first = manifest_of(do_run(cli, good_config, tmp_path / "runs"))
    second = manifest_of(do_run(cli, good_config, tmp_path / "runs"))
    assert first["counts"].get("cached", 0) == 0
    assert second["counts"].get("cached", 0) == 0  # the overlay of the first job is gone
    assert not shared_db(tmp_path).exists()


def test_a_candidate_with_main_s_self_reported_identity_gets_no_cache_hit(
    cli: CliRunner,
    good: TargetCassette,
    good_config: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared_run(cli, good_config, tmp_path, monkeypatch)  # main fills its cache
    before = shared_db(tmp_path).read_bytes()
    monkeypatch.setenv("PRUEFSTAND_CACHE_MODE", "overlay")  # a PR: same self-reported identity
    pr = manifest_of(do_run(cli, good_config, tmp_path / "runs"))
    assert pr["counts"].get("cached", 0) == 0
    assert "cached_from_base" not in pr["counts"]
    assert shared_db(tmp_path).read_bytes() == before


def test_a_pr_run_with_the_trusted_id_of_main_reads_the_main_cache_and_leaves_it_untouched(
    cli: CliRunner,
    good: TargetCassette,
    good_config: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRUEFSTAND_TRUSTED_TARGET_ID", TRUSTED)
    shared_run(cli, good_config, tmp_path, monkeypatch)
    before = shared_db(tmp_path).read_bytes()
    monkeypatch.setenv("PRUEFSTAND_CACHE_MODE", "overlay")
    temp = tmp_path / "tmp"
    temp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(temp))
    pr = manifest_of(do_run(cli, good_config, tmp_path / "runs"))
    assert pr["counts"]["cached"] == pr["n_cases"]
    assert pr["counts"]["cached_from_base"] == pr["n_cases"]
    assert shared_db(tmp_path).read_bytes() == before
    assert list(temp.iterdir()) == []


def test_a_different_trusted_id_misses_even_with_the_same_self_reported_identity(
    cli: CliRunner,
    good: TargetCassette,
    good_config: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRUEFSTAND_TRUSTED_TARGET_ID", TRUSTED)
    shared_run(cli, good_config, tmp_path, monkeypatch)
    monkeypatch.setenv("PRUEFSTAND_TRUSTED_TARGET_ID", "sha256:" + "b" * 64)
    other = shared_run(cli, good_config, tmp_path, monkeypatch)
    assert other["counts"].get("cached", 0) == 0


def test_the_trusted_id_changes_the_fingerprint_it_never_replaces_the_reported_one(
    cli: CliRunner,
    good: TargetCassette,
    good_config: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plain = shared_run(cli, good_config, tmp_path, monkeypatch)["target_fingerprint"]
    monkeypatch.setenv("PRUEFSTAND_TRUSTED_TARGET_ID", TRUSTED)
    trusted = shared_run(cli, good_config, tmp_path, monkeypatch)["target_fingerprint"]
    assert trusted != plain


def test_a_target_without_a_usable_identity_gets_no_cache_at_all(
    cli: CliRunner,
    opaque: TargetCassette,
    good_config: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = shared_run(cli, good_config, tmp_path, monkeypatch)
    second = shared_run(cli, good_config, tmp_path, monkeypatch)
    assert first["counts"].get("cached", 0) == 0
    assert second["counts"].get("cached", 0) == 0
    assert not shared_db(tmp_path).exists()  # neither read nor written


def test_an_invalid_trusted_id_is_a_usage_error(
    cli: CliRunner,
    good: TargetCassette,
    good_config: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRUEFSTAND_TRUSTED_TARGET_ID", "bad id; rm -rf")
    result = do_run(cli, good_config, tmp_path / "runs")
    assert result.exit_code == 2
    assert "PRUEFSTAND_TRUSTED_TARGET_ID" in result.output


def test_an_invalid_cache_mode_is_a_usage_error(
    cli: CliRunner,
    good: TargetCassette,
    good_config: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRUEFSTAND_CACHE_MODE", "bogus")
    result = do_run(cli, good_config, tmp_path / "runs")
    assert result.exit_code == 2
    assert "PRUEFSTAND_CACHE_MODE" in result.output


def test_a_main_rerun_in_shared_mode_with_the_trusted_id_is_not_counted_as_base_hits(
    cli: CliRunner,
    good: TargetCassette,
    good_config: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRUEFSTAND_TRUSTED_TARGET_ID", TRUSTED)
    shared_run(cli, good_config, tmp_path, monkeypatch)
    second = shared_run(cli, good_config, tmp_path, monkeypatch)
    assert second["counts"]["cached"] == second["n_cases"]  # a full cache rerun on main
    assert "cached_from_base" not in second["counts"]  # its own cache, not a base overlay
