"""``pruefstand baseline promote | export-public | prune | publish-dashboard`` (T6.1 S7)."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from click.testing import Result
from pruefstand.store.baselines_local import LocalDirBaselineStore
from testsupport.pipeline_support import config_file, mini_config
from testsupport.run_builders import make_case
from testsupport.store_support import (
    FP,
    registry,
    release_run,
    results_for,
    run_id,
    run_of,
    token,
)
from typer.testing import CliRunner

from pruefstand.cli import app
from pruefstand.core.config import BaselineStoreConfig
from pruefstand.core.models.run import RunArtifacts
from pruefstand.store.artifacts import ArtifactStore


def write(tmp_path: Path, run: RunArtifacts) -> Path:
    root = tmp_path / "runs"
    return ArtifactStore(root).write_run(run.model_copy(update={"root": root / run.root.name}))


def config(tmp_path: Path) -> Path:
    store = BaselineStoreConfig(type="local_dir", path=tmp_path / "store")
    return config_file(tmp_path / "cfg.yaml", mini_config(baseline_store=store))


def promote(cli: CliRunner, tmp_path: Path, run_dir: Path, ref: str) -> Result:
    args = ["baseline", "promote", "--run", str(run_dir), "--ref", ref]
    return cli.invoke(app, [*args, "--config", str(config(tmp_path))])


def store_of(tmp_path: Path) -> LocalDirBaselineStore:
    return LocalDirBaselineStore(tmp_path / "store")


def test_promoting_a_complete_run_makes_it_the_baseline(cli: CliRunner, tmp_path: Path) -> None:
    result = promote(cli, tmp_path, write(tmp_path, run_of(tmp_path, 1)), "main")
    assert result.exit_code == 0, result.output
    back = store_of(tmp_path).get(FP, "main")
    assert back is not None
    assert back.results.manifest.run_id == run_id(1)
    assert FP in result.output


@pytest.mark.parametrize(
    "changes",
    [
        {"complete": False, "stop_reason": "budget_exceeded"},
        {"complete": False, "stop_reason": "aborted"},
        {"complete": False, "stop_reason": "aborted", "infra_error": "ollama_down: no answer"},
    ],
)
def test_an_incomplete_run_is_refused_with_exit_one(
    cli: CliRunner, tmp_path: Path, changes: dict[str, Any]
) -> None:
    store_of(tmp_path).put(run_of(tmp_path, 1), "main")
    result = promote(cli, tmp_path, write(tmp_path, run_of(tmp_path, 2, **changes)), "main")
    assert result.exit_code == 1
    assert "complete" in result.output
    back = store_of(tmp_path).get(FP, "main")
    assert back is not None
    assert back.results.manifest.run_id == run_id(1)


def test_a_judge_fallback_run_is_refused_and_the_previous_baseline_stays(
    cli: CliRunner, tmp_path: Path
) -> None:
    store_of(tmp_path).put(run_of(tmp_path, 1), "main")
    flagged = write(tmp_path, run_of(tmp_path, 2, judge_fallback=True))
    result = promote(cli, tmp_path, flagged, "main")
    assert result.exit_code == 1
    assert "judge fallback" in result.output
    assert "not promoted" in result.output
    back = store_of(tmp_path).get(FP, "main")
    assert back is not None
    assert back.results.manifest.run_id == run_id(1)


@pytest.mark.parametrize(
    ("changes", "name"),
    [
        ({"judge_drift": True}, "judge_drift"),
        ({"judge_degraded": True}, "judge_degraded"),
        ({"counts": {"ok": 2, "judge_truncated": 2}, "judged_cases": 2}, "judge_truncated"),
    ],
)
def test_flagged_runs_name_the_flag(
    cli: CliRunner, tmp_path: Path, changes: dict[str, Any], name: str
) -> None:
    result = promote(cli, tmp_path, write(tmp_path, run_of(tmp_path, 2, **changes)), "main")
    assert result.exit_code == 1
    assert name in result.output
    assert store_of(tmp_path).get(FP, "main") is None


@pytest.mark.parametrize("ref", ["release", "nightly-b3", "latest", "../main"])
def test_an_unknown_ref_is_a_usage_error(cli: CliRunner, tmp_path: Path, ref: str) -> None:
    result = promote(cli, tmp_path, write(tmp_path, run_of(tmp_path, 1)), ref)
    assert result.exit_code == 2


def test_the_block_rules_are_usage_errors(cli: CliRunner, tmp_path: Path) -> None:
    block_run = write(tmp_path, run_of(tmp_path, 1, block=1))
    assert promote(cli, tmp_path, block_run, "release-b1").exit_code == 2
    assert promote(cli, tmp_path, block_run, "nightly-b2").exit_code == 2
    assert promote(cli, tmp_path, block_run, "main").exit_code == 2
    assert promote(cli, tmp_path, block_run, "nightly-b1").exit_code == 0


def test_the_release_run_is_promoted_as_a_block_projection(cli: CliRunner, tmp_path: Path) -> None:
    release = write(tmp_path, release_run(tmp_path))
    result = promote(cli, tmp_path, release, "release-b1")
    assert result.exit_code == 0, result.output
    stored = [p for p in (tmp_path / "store").iterdir() if (p / "release-b1").is_dir()]
    assert len(stored) == 1
    back = store_of(tmp_path).get(stored[0].name, "release-b1")
    assert back is not None
    assert back.results.manifest.block == 1
    assert len(back.results.values) == 4
    assert stored[0].name != FP  # the projection has the block-1 fingerprint


def test_a_missing_run_is_a_runtime_error(cli: CliRunner, tmp_path: Path) -> None:
    result = promote(cli, tmp_path, tmp_path / "runs" / "nope", "main")
    assert result.exit_code == 3


# --- export-public -----------------------------------------------------------------------------


def registry_file(root: Path) -> None:
    target = root / "corpus" / "slice_v1" / "canaries.public.json"
    target.parent.mkdir(parents=True)
    target.write_text(registry("VN-7f3a9c").model_dump_json(), encoding="utf-8")


def test_export_public_writes_a_directory_without_canaries(
    cli: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry_file(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PRUEFSTAND_HELDOUT_DIR", raising=False)
    cases = [
        make_case(0),
        make_case(1, category="leak_probe", forbidden_strings=[token("VN-7f3a9c")]),
    ]
    results = results_for(cases, run_id=run_id(3), eval_fingerprint=FP)
    run = RunArtifacts(results=results, root=tmp_path / "runs" / run_id(3))
    out = tmp_path / "pub"
    args = ["baseline", "export-public", "--run", str(write(tmp_path, run)), "--out", str(out)]
    result = cli.invoke(app, args)
    assert result.exit_code == 0, result.output
    assert json.loads((out / "manifest.json").read_text(encoding="utf-8"))["sanitised"] is True
    for path in out.iterdir():
        assert b"CANARY-" not in path.read_bytes()


def test_export_public_without_any_registry_fails_closed(
    cli: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PRUEFSTAND_HELDOUT_DIR", raising=False)
    args = ["baseline", "export-public", "--run", str(write(tmp_path, run_of(tmp_path, 1)))]
    result = cli.invoke(app, [*args, "--out", str(tmp_path / "pub")])
    assert result.exit_code == 3
    assert not (tmp_path / "pub").exists()


# --- prune -------------------------------------------------------------------------------------


def test_prune_prints_the_removed_ids_and_updates_nothing_else(
    cli: CliRunner, tmp_path: Path
) -> None:
    start = datetime.now(UTC) - timedelta(days=1)
    state = {"n": 0}

    def tick() -> datetime:
        state["n"] += 1
        return start + timedelta(seconds=state["n"])

    store = LocalDirBaselineStore(tmp_path / "store", clock=tick)
    for i in range(1, 24):
        store.put(run_of(tmp_path, i), "main")
    result = cli.invoke(
        app, ["baseline", "prune", "--keep", "20", "--config", str(config(tmp_path))]
    )
    assert result.exit_code == 0, result.output
    for i in (1, 2, 3):
        assert run_id(i) in result.output
    assert run_id(4) not in result.output
    again = cli.invoke(
        app, ["baseline", "prune", "--keep", "20", "--config", str(config(tmp_path))]
    )
    assert again.exit_code == 0
    assert run_id(1) not in again.output


def test_prune_rejects_a_non_positive_keep(cli: CliRunner, tmp_path: Path) -> None:
    result = cli.invoke(
        app, ["baseline", "prune", "--keep", "0", "--config", str(config(tmp_path))]
    )
    assert result.exit_code == 2


# --- publish-dashboard -------------------------------------------------------------------------


def test_publish_dashboard_refuses_an_unsanitised_directory_before_any_network(
    cli: CliRunner, tmp_path: Path
) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "run.json").write_text("{}", encoding="utf-8")
    result = cli.invoke(
        app, ["baseline", "publish-dashboard", "--src", str(src), "--repo", "owner/data"]
    )
    assert result.exit_code == 3
    assert "sanitise" in result.output


def test_publish_dashboard_rejects_a_bad_repo_name(cli: CliRunner, tmp_path: Path) -> None:
    result = cli.invoke(
        app, ["baseline", "publish-dashboard", "--src", str(tmp_path), "--repo", "not a repo"]
    )
    assert result.exit_code == 2
