"""``pruefstand run`` with the target cache: shared for main, overlay for PRs (T6.1 S3, Done-when)."""

import tempfile
from pathlib import Path

import pytest
from testsupport.cli_support import do_run, manifest_of
from testsupport.target_cassette import TargetCassette
from typer.testing import CliRunner


def shared_db(tmp_path: Path) -> Path:
    return tmp_path / "cache" / "target" / "cache.sqlite3"


@pytest.fixture(autouse=True)
def _cache_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PRUEFSTAND_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.delenv("PRUEFSTAND_CACHE_MODE", raising=False)


def test_a_second_shared_run_is_answered_entirely_from_the_cache(
    cli: CliRunner,
    good: TargetCassette,
    good_config: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRUEFSTAND_CACHE_MODE", "shared")
    first = manifest_of(do_run(cli, good_config, tmp_path / "runs"))
    second = manifest_of(do_run(cli, good_config, tmp_path / "runs"))
    assert first["counts"].get("cached", 0) == 0
    assert second["counts"]["cached"] == second["n_cases"]
    assert second["target_fingerprint"] == first["target_fingerprint"]


def test_the_default_overlay_mode_never_writes_the_shared_cache(
    cli: CliRunner, good: TargetCassette, good_config: Path, tmp_path: Path
) -> None:
    first = manifest_of(do_run(cli, good_config, tmp_path / "runs"))
    second = manifest_of(do_run(cli, good_config, tmp_path / "runs"))
    assert first["counts"].get("cached", 0) == 0
    assert second["counts"].get("cached", 0) == 0  # the overlay of the first job is gone
    assert not shared_db(tmp_path).exists()


def test_a_pr_run_reads_the_main_cache_and_leaves_it_untouched(
    cli: CliRunner,
    good: TargetCassette,
    good_config: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRUEFSTAND_CACHE_MODE", "shared")
    manifest_of(do_run(cli, good_config, tmp_path / "runs"))
    before = shared_db(tmp_path).read_bytes()
    monkeypatch.setenv("PRUEFSTAND_CACHE_MODE", "overlay")
    temp = tmp_path / "tmp"
    temp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(temp))
    pr = manifest_of(do_run(cli, good_config, tmp_path / "runs"))
    assert pr["counts"]["cached"] == pr["n_cases"]
    assert shared_db(tmp_path).read_bytes() == before
    assert list(temp.iterdir()) == []


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
