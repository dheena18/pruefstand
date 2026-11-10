"""Opus review of #143 (D1120, D1123): race, no_baseline, --reason rules, golden bytes."""

import hashlib
import json
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
from testsupport.pipeline_support import config_file, mini_config
from testsupport.promote_support import (
    OTHER,
    RUN,
    promote,
    promote_store_test,
    promoted,
    stored,
    write_gate,
)
from testsupport.store_support import FP, run_of
from typer.testing import CliRunner

from pruefstand.cli import app
from pruefstand.core.config import BaselineStoreConfig
from pruefstand.core.enums import GateStatus
from pruefstand.core.models.baseline import ExpectedBaseline
from pruefstand.store._baseline_write import promote_to_disk
from pruefstand.store.artifacts import ArtifactStore
from pruefstand.store.baseline_index import BaselineIndex, IndexEntry, with_promotion
from pruefstand.store.baselines_git import GitBranchBaselineStore
from pruefstand.store.baselines_local import LocalDirBaselineStore
from pruefstand.store.promote import BaselineRefused

AT = datetime(2026, 11, 10, 8, 0, tzinfo=UTC)


@pytest.fixture
def cli() -> CliRunner:
    return CliRunner()


def first_baseline(cli: CliRunner, tmp_path: Path) -> None:
    base = stored(tmp_path, run_id=OTHER)
    write_gate(base, GateStatus.INSUFFICIENT_DATA)
    assert promote(cli, tmp_path, base).exit_code == 0


def race(store: LocalDirBaselineStore, runs: list[Path], expected: str | None) -> list[str]:
    """Promote every run at once against ``expected``; the outcome of each."""
    barrier, outcome = threading.Barrier(len(runs)), [""] * len(runs)

    def one(index: int) -> None:
        artifacts = ArtifactStore(runs[index].parent).read_run(runs[index])
        barrier.wait()
        try:
            store.put(artifacts, "main", expected=ExpectedBaseline(run_id=expected))
            outcome[index] = "promoted"
        except BaselineRefused:
            outcome[index] = "refused"

    threads = [threading.Thread(target=one, args=(i,)) for i in range(len(runs))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return sorted(outcome)


def test_two_concurrent_first_promotes_store_exactly_one(tmp_path: Path) -> None:
    runs = [stored(tmp_path, run_id=RUN), stored(tmp_path, run_id=OTHER)]
    store = LocalDirBaselineStore(tmp_path / "store")
    assert race(store, runs, None) == ["promoted", "refused"]


def test_two_concurrent_promotes_over_the_same_baseline_store_exactly_one(tmp_path: Path) -> None:
    base = ArtifactStore(tmp_path / "runs").read_run(
        stored(tmp_path, run_id="20261101T220000-aaaaaa")
    )
    store = LocalDirBaselineStore(tmp_path / "store")
    store.put(base, "main")
    runs = [stored(tmp_path, run_id=RUN), stored(tmp_path, run_id=OTHER)]
    assert race(store, runs, "20261101T220000-aaaaaa") == ["promoted", "refused"]


def test_the_git_store_rechecks_the_fresh_index_and_rolls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = GitBranchBaselineStore("owner/repo", tmp_path / "root", token_env=None)
    (tmp_path / "root").mkdir()
    monkeypatch.setattr(store, "_check_root", lambda: None)  # no sentinel in this test
    entry = IndexEntry(run_id=OTHER, manifest_sha256="0" * 64, promoted_at=AT)
    moved = with_promotion(BaselineIndex.empty(), FP, "main", entry)  # another promote won

    def publish(change: Callable[[BaselineIndex], BaselineIndex], _message: str) -> None:
        change(moved)  # the store's index change function

    monkeypatch.setattr(store, "_publish", publish)  # no remote in a unit test
    artifacts = ArtifactStore(tmp_path / "runs").read_run(stored(tmp_path))
    with pytest.raises(BaselineRefused, match="changed during the promote"):
        store.put(artifacts, "main", expected=ExpectedBaseline(run_id=None))
    assert not (tmp_path / "root" / FP / "main").exists()  # rolled back


def test_no_baseline_after_the_first_promote_is_never_waived(
    cli: CliRunner, tmp_path: Path
) -> None:
    first_baseline(cli, tmp_path)
    run = stored(tmp_path)
    write_gate(run, GateStatus.INSUFFICIENT_DATA)
    for extra in ((), ("--allow-failed-gate",)):
        result = promote(cli, tmp_path, run, *extra)
        assert result.exit_code == 1
        assert "no baseline" in result.output
    assert not promoted(tmp_path)


def test_unsupported_config_is_refused_and_waivable(cli: CliRunner, tmp_path: Path) -> None:
    first_baseline(cli, tmp_path)
    run = stored(tmp_path)
    write_gate(run, GateStatus.UNSUPPORTED_CONFIG, against=OTHER)
    result = promote(cli, tmp_path, run)
    assert result.exit_code == 1
    assert "UNSUPPORTED_CONFIG" in result.output
    assert promote(cli, tmp_path, run, "--allow-failed-gate").exit_code == 0


@pytest.mark.parametrize("reason", ["ok\x1b[31m", "zero\u200bwidth", "bidi" + chr(0x202E) + "evil"])
def test_a_reason_with_control_or_format_characters_is_refused(
    cli: CliRunner, tmp_path: Path, reason: str
) -> None:
    run = stored(tmp_path)
    write_gate(run, GateStatus.FAIL)
    result = promote(cli, tmp_path, run, "--allow-failed-gate", "--reason", reason)
    assert result.exit_code == 2
    assert not promoted(tmp_path)


def test_a_reason_without_the_flag_is_refused(cli: CliRunner, tmp_path: Path) -> None:
    run = stored(tmp_path)
    write_gate(run)
    assert promote(cli, tmp_path, run, "--reason", "why").exit_code == 2
    assert not promoted(tmp_path)


def test_the_nightly_ref_is_bound_to_its_own_stored_baseline(
    cli: CliRunner, tmp_path: Path
) -> None:
    store = BaselineStoreConfig(type="local_dir", path=tmp_path / "store")
    cfg = config_file(tmp_path / "cfg.yaml", mini_config(baseline_store=store))
    root = tmp_path / "runs"
    first = ArtifactStore(root).write_run(run_of(tmp_path, 1, block=1))
    assert promote_store_test(cli, first, "nightly-b1", cfg, tmp_path / "store").exit_code == 0
    second = ArtifactStore(root).write_run(run_of(tmp_path, 2, block=1))
    write_gate(second, against=RUN, eval_fingerprint=FP)  # not the stored nightly-b1 run
    args = [
        "baseline",
        "promote",
        "--run",
        str(second),
        "--ref",
        "nightly-b1",
        "--config",
        str(cfg),
    ]
    result = cli.invoke(app, args)
    assert result.exit_code == 1
    assert "not the stored baseline" in result.output


def test_a_plain_promotion_keeps_its_manifest_bytes(tmp_path: Path) -> None:
    artifacts = ArtifactStore(tmp_path / "runs").read_run(stored(tmp_path))
    (tmp_path / "root").mkdir()
    promotion = promote_to_disk(tmp_path / "root", artifacts, "main", lambda: AT)
    promotion.commit()
    raw = (tmp_path / "root" / FP / "main" / "manifest.json").read_bytes()
    files = {
        name: hashlib.sha256((tmp_path / "root" / FP / "main" / name).read_bytes()).hexdigest()
        for name in ("results.parquet", "responses.jsonl.zst", "run.json", "scored.jsonl.zst")
    }
    golden = {
        "eval_fingerprint": FP,
        "files": files,
        "git_sha": artifacts.results.manifest.git_sha,
        "promoted_at": "2026-11-10T08:00:00Z",
        "ref": "main",
        "run_id": RUN,
        "schema_version": "1",
    }
    assert raw == (json.dumps(golden, indent=2, sort_keys=True) + "\n").encode("utf-8")


def test_store_promotions_without_the_flag_record_no_override(
    cli: CliRunner, tmp_path: Path
) -> None:
    first_baseline(cli, tmp_path)
    run = stored(tmp_path)
    write_gate(run, against=OTHER)
    assert promote(cli, tmp_path, run).exit_code == 0
    manifest = json.loads((tmp_path / "store" / FP / "main" / "manifest.json").read_text("utf-8"))
    assert "override" not in manifest
    assert manifest["run_id"] == RUN
