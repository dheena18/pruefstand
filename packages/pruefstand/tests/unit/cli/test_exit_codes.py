"""Exit codes of every command (interfaces §15): 0 pass/warn, 1 fail, 2 usage/config, 3 runtime."""

from pathlib import Path
from typing import Any

import pytest
from testsupport.builders import fixture_f0, make_record, make_run
from testsupport.pipeline_support import config_file, mini_config
from typer.testing import CliRunner

from pruefstand.cli import app
from pruefstand.cli import run as cli_run
from pruefstand.core.config import GatePolicy, MetricPolicy
from pruefstand.core.errors import (
    ConfigError,
    CorpusMismatch,
    DatasetError,
    GateInputError,
    StoreError,
)
from pruefstand.core.models.run import RunArtifacts
from pruefstand.runner.runner import Runner
from pruefstand.store.artifacts import ArtifactStore

KEEP = {"context_recall", "error_rate", "tenant_leak", "canary_leak", "system_prompt_leak"}
POLICY = GatePolicy(metrics={"context_recall": MetricPolicy(max_drop=0.05)}, n_resamples=300)


def stored(root: Path, run_id: str, **kwargs: Any) -> Path:
    cases, values = fixture_f0()
    values = {m: v for m, v in values.items() if m in KEEP}
    run = make_run(run_id, cases, values, records=[make_record(c) for c in cases], **kwargs)
    return ArtifactStore(root).write_run(RunArtifacts(results=run, root=root / run_id))


@pytest.fixture
def gate_config(tmp_path: Path) -> Path:
    return config_file(tmp_path / "gate.yaml", mini_config(gate=POLICY))


def test_a_warning_passes_unless_fail_on_warn(tmp_path: Path, gate_config: Path) -> None:
    base = stored(tmp_path, "20261102T220000-aaaaaa")
    cand = stored(tmp_path, "20261102T220001-bbbbbb", counts={"unsupported_config": 1})
    args = ["gate", "--config", str(gate_config), "--candidate", str(cand), "--baseline", str(base)]
    assert CliRunner().invoke(app, args).exit_code == 0
    assert CliRunner().invoke(app, [*args, "--fail-on-warn"]).exit_code == 1


def test_a_clean_pass_stays_zero_with_fail_on_warn(tmp_path: Path, gate_config: Path) -> None:
    base = stored(tmp_path, "20261102T220000-aaaaaa")
    cand = stored(tmp_path, "20261102T220001-bbbbbb")
    args = ["gate", "--config", str(gate_config), "--candidate", str(cand), "--baseline", str(base)]
    assert CliRunner().invoke(app, [*args, "--fail-on-warn"]).exit_code == 0


def test_a_gate_fail_is_exit_one(tmp_path: Path, gate_config: Path) -> None:
    base = stored(tmp_path, "20261102T220000-aaaaaa")
    cases, values = fixture_f0()
    cand = stored(tmp_path, "20261102T220001-bbbbbb")  # same values, so fail via a hard fail below
    leak = tmp_path / "leaky"
    leaky_values = {m: list(v) for m, v in values.items() if m in KEEP}
    leaky_values["tenant_leak"][0] = 1.0
    run = make_run(
        "20261102T220002-cccccc", cases, leaky_values, records=[make_record(c) for c in cases]
    )
    ArtifactStore(leak).write_run(RunArtifacts(results=run, root=leak / "20261102T220002-cccccc"))
    args = ["gate", "--config", str(gate_config), "--baseline", str(base)]
    result = CliRunner().invoke(app, [*args, "--candidate", str(leak / "20261102T220002-cccccc")])
    assert result.exit_code == 1
    assert cand.is_dir()


def test_no_baseline_given_is_a_usage_error(tmp_path: Path, gate_config: Path) -> None:
    cand = stored(tmp_path, "20261102T220001-bbbbbb")
    result = CliRunner().invoke(
        app, ["gate", "--config", str(gate_config), "--candidate", str(cand)]
    )
    assert result.exit_code == 2


def test_baseline_and_from_store_together_are_a_usage_error(
    tmp_path: Path, gate_config: Path
) -> None:
    cand = stored(tmp_path, "20261102T220001-bbbbbb")
    args = ["gate", "--config", str(gate_config), "--candidate", str(cand), "--baseline", str(cand)]
    assert CliRunner().invoke(app, [*args, "--from-store"]).exit_code == 2


def test_from_store_is_not_implemented_yet(tmp_path: Path, gate_config: Path) -> None:
    cand = stored(tmp_path, "20261102T220001-bbbbbb")
    args = ["gate", "--config", str(gate_config), "--candidate", str(cand), "--from-store"]
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 2
    assert "T6.1" in result.output


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (ConfigError("bad config"), 2),
        (CorpusMismatch("other corpus"), 1),
        (StoreError("disk"), 3),
        (GateInputError("mismatch"), 3),
        (DatasetError("row"), 3),
    ],
)
def test_pruefstand_errors_map_to_exit_codes(
    error: Exception, code: int, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def boom(*args: object, **kwargs: object) -> None:
        raise error

    monkeypatch.setattr(cli_run, "run_eval", boom)
    cfg = config_file(tmp_path / "c.yaml", mini_config())
    result = CliRunner().invoke(
        app, ["run", "--config", str(cfg), "--tier", "pr", "--out", str(tmp_path / "r")]
    )
    assert result.exit_code == code
    assert str(error) in result.output
    assert "Traceback" not in result.output
    assert result.stdout == ""  # errors go to stderr


def test_an_unexpected_exception_is_exit_three_without_a_traceback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, good: object
) -> None:
    async def boom(self: Runner, *args: object, **kwargs: object) -> None:
        message = "kaputt"
        raise RuntimeError(message)

    monkeypatch.setattr(Runner, "run", boom)
    cfg = config_file(tmp_path / "c.yaml", mini_config())
    args = ["run", "--config", str(cfg), "--tier", "pr", "--out", str(tmp_path / "r")]
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 3
    assert "Traceback" not in result.output
    assert "RuntimeError" in result.output


def test_verbose_shows_the_traceback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, good: object
) -> None:
    async def boom(self: Runner, *args: object, **kwargs: object) -> None:
        message = "kaputt"
        raise RuntimeError(message)

    monkeypatch.setattr(Runner, "run", boom)
    cfg = config_file(tmp_path / "c.yaml", mini_config())
    args = ["--verbose", "run", "--config", str(cfg), "--tier", "pr", "--out", str(tmp_path / "r")]
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 3
    assert "Traceback" in result.output


def test_a_missing_option_is_a_usage_error() -> None:
    assert CliRunner().invoke(app, ["run", "--tier", "pr"]).exit_code == 2
    assert (
        CliRunner()
        .invoke(app, ["run", "--config", "x.yaml", "--tier", "weekly", "--out", "o"])
        .exit_code
        == 2
    )


@pytest.mark.parametrize(
    ("args", "needle"),
    [
        (["ingest", "--config", "c.yaml", "--out", "corpus/"], "T2.5"),
        (["build-dataset", "--config", "d.yaml"], "T4.7a"),
        (["baseline", "promote", "--run", "runs/x", "--ref", "main"], "T6.1"),
    ],
)
def test_stub_commands_exit_two(args: list[str], needle: str) -> None:
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 2
    assert "not implemented yet" in result.output
    assert needle in result.output
