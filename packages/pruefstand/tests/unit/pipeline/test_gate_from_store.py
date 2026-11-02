"""``gate --from-store`` without and with a baseline; the canary registry source (T6.1 S7)."""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from testsupport.pipeline_support import config_file, mini_config
from testsupport.store_support import gate_run, registry, token, write_gate_run
from typer.testing import CliRunner, Result

from pruefstand.cli import app
from pruefstand.core.config import BaselineStoreConfig, GatePolicy, MetricPolicy
from pruefstand.core.enums import GateStatus
from pruefstand.core.errors import StoreError
from pruefstand.core.logging import configure_logging
from pruefstand.core.models.gate import GateReport
from pruefstand.store.baselines_local import LocalDirBaselineStore
from pruefstand.store.canary_source import load_canary_registry

FP = "feedfacefeedface"
POLICY = GatePolicy(
    metrics={
        "context_recall": MetricPolicy(max_drop=0.05),
        "error_rate": MetricPolicy(max_value=0.02),
    },
    n_resamples=500,
)


def config(tmp_path: Path) -> Path:
    store = BaselineStoreConfig(type="local_dir", path=tmp_path / "store")
    return config_file(tmp_path / "cfg.yaml", mini_config(gate=POLICY, baseline_store=store))


@pytest.fixture
def cli() -> Iterator[CliRunner]:
    yield CliRunner()
    configure_logging()


def invoke(cli: CliRunner, tmp_path: Path, candidate: Path, *extra: str) -> Result:
    args = ["gate", "--config", str(config(tmp_path)), "--candidate", str(candidate)]
    return cli.invoke(app, [*args, "--from-store", *extra])


@pytest.mark.parametrize("workload", ["pr", "nightly"])
def test_an_empty_store_gives_no_baseline_and_exit_zero(
    cli: CliRunner, tmp_path: Path, workload: str
) -> None:
    candidate = write_gate_run(
        tmp_path / "runs", "20261102T220001-bbbbbb", fp=FP, workload=workload
    )
    result = invoke(cli, tmp_path, candidate)
    assert result.exit_code == 0, result.output
    report = GateReport.model_validate_json((candidate / "gate.json").read_text(encoding="utf-8"))
    assert report.status is GateStatus.INSUFFICIENT_DATA
    assert report.no_baseline is True
    assert report.baseline_run_id is None
    assert report.decisions == ()
    assert f"no baseline for {FP}" in result.output
    assert "run baseline-promote" in result.output


def test_a_baseline_in_the_store_is_used(cli: CliRunner, tmp_path: Path) -> None:
    store = LocalDirBaselineStore(tmp_path / "store")
    store.put(gate_run(tmp_path / "base", "20261102T220000-aaaaaa", fp=FP), "main")
    candidate = write_gate_run(tmp_path / "runs", "20261102T220001-bbbbbb", fp=FP)
    result = invoke(cli, tmp_path, candidate, "--ref", "main")
    assert result.exit_code == 0, result.output
    report = GateReport.model_validate_json((candidate / "gate.json").read_text(encoding="utf-8"))
    assert report.no_baseline is False
    assert report.baseline_run_id == "20261102T220000-aaaaaa"
    assert report.status is GateStatus.PASS


def test_the_default_ref_is_main(cli: CliRunner, tmp_path: Path) -> None:
    LocalDirBaselineStore(tmp_path / "store").put(
        gate_run(tmp_path / "base", "20261102T220000-aaaaaa", fp=FP), "main"
    )
    candidate = write_gate_run(tmp_path / "runs", "20261102T220001-bbbbbb", fp=FP)
    assert invoke(cli, tmp_path, candidate).exit_code == 0
    assert json.loads((candidate / "gate.json").read_text(encoding="utf-8"))["no_baseline"] is False


def test_a_baseline_of_the_other_stack_is_refused(cli: CliRunner, tmp_path: Path) -> None:
    LocalDirBaselineStore(tmp_path / "store").put(
        gate_run(tmp_path / "base", "20261102T220000-aaaaaa", fp=FP, stack="live"), "main"
    )
    candidate = write_gate_run(tmp_path / "runs", "20261102T220001-bbbbbb", fp=FP, stack="a40")
    result = invoke(cli, tmp_path, candidate)
    assert result.exit_code == 3
    assert "stack" in result.output


def test_a_tampered_store_baseline_is_a_runtime_error_not_a_pass(
    cli: CliRunner, tmp_path: Path
) -> None:
    store = LocalDirBaselineStore(tmp_path / "store")
    store.put(gate_run(tmp_path / "base", "20261102T220000-aaaaaa", fp=FP), "main")
    target = tmp_path / "store" / FP / "main" / "results.parquet"
    target.write_bytes(target.read_bytes() + b"x")
    candidate = write_gate_run(tmp_path / "runs", "20261102T220001-bbbbbb", fp=FP)
    result = invoke(cli, tmp_path, candidate)
    assert result.exit_code == 3
    assert not (candidate / "gate.json").exists()


def test_from_store_and_baseline_together_are_a_usage_error(cli: CliRunner, tmp_path: Path) -> None:
    candidate = write_gate_run(tmp_path / "runs", "20261102T220001-bbbbbb", fp=FP)
    other = write_gate_run(tmp_path / "runs", "20261102T220000-aaaaaa", fp=FP)
    result = invoke(cli, tmp_path, candidate, "--baseline", str(other))
    assert result.exit_code == 2


def test_ref_without_from_store_is_a_usage_error(cli: CliRunner, tmp_path: Path) -> None:
    candidate = write_gate_run(tmp_path / "runs", "20261102T220001-bbbbbb", fp=FP)
    other = write_gate_run(tmp_path / "runs", "20261102T220000-aaaaaa", fp=FP)
    args = ["gate", "--config", str(config(tmp_path)), "--candidate", str(candidate)]
    result = cli.invoke(app, [*args, "--baseline", str(other), "--ref", "main"])
    assert result.exit_code == 2


def test_an_unknown_ref_is_a_usage_error(cli: CliRunner, tmp_path: Path) -> None:
    candidate = write_gate_run(tmp_path / "runs", "20261102T220001-bbbbbb", fp=FP)
    assert invoke(cli, tmp_path, candidate, "--ref", "release").exit_code == 2


# --- canary registry source --------------------------------------------------------------------


def test_no_registry_file_is_a_store_error(tmp_path: Path) -> None:
    with pytest.raises(StoreError, match="canary"):
        load_canary_registry(root=tmp_path, env={})


def write_registry(path: Path, *names: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(registry(*names).model_dump_json(), encoding="utf-8")


def test_the_slice_file_and_a_heldout_file_are_merged(tmp_path: Path) -> None:
    write_registry(tmp_path / "corpus" / "slice_v1" / "canaries.public.json", "A1", "A2")
    write_registry(tmp_path / "datasets" / "canaries" / "v2" / "canaries.json", "B1")
    held = tmp_path / "held"
    write_registry(held / "canaries_heldout.json", "H1")
    merged = load_canary_registry(root=tmp_path, env={"PRUEFSTAND_HELDOUT_DIR": str(held)})
    assert {c.token for c in merged.canaries} == {token(n) for n in ("A1", "A2", "B1", "H1")}


def test_without_the_heldout_dir_only_the_public_files_are_read(tmp_path: Path) -> None:
    write_registry(tmp_path / "corpus" / "slice_v1" / "canaries.public.json", "A1")
    merged = load_canary_registry(root=tmp_path, env={})
    assert [c.token for c in merged.canaries] == [token("A1")]


def test_a_missing_heldout_file_is_an_error_when_the_dir_is_named(tmp_path: Path) -> None:
    write_registry(tmp_path / "corpus" / "slice_v1" / "canaries.public.json", "A1")
    with pytest.raises(StoreError, match="held-out"):
        load_canary_registry(root=tmp_path, env={"PRUEFSTAND_HELDOUT_DIR": str(tmp_path / "nope")})


def test_a_broken_registry_file_fails_closed_without_echoing_its_text(tmp_path: Path) -> None:
    broken = tmp_path / "corpus" / "slice_v1" / "canaries.public.json"
    broken.parent.mkdir(parents=True)
    broken.write_text('{"secret-looking": 1}', encoding="utf-8")
    with pytest.raises(StoreError) as excinfo:
        load_canary_registry(root=tmp_path, env={})
    assert "secret-looking" not in str(excinfo.value)


def test_an_oversized_registry_file_is_refused(tmp_path: Path) -> None:
    big = tmp_path / "corpus" / "slice_v1" / "canaries.public.json"
    big.parent.mkdir(parents=True)
    big.write_bytes(b" " * (9 * 1024 * 1024))
    with pytest.raises(StoreError, match="larger than"):
        load_canary_registry(root=tmp_path, env={})


def test_a_symlinked_registry_file_is_refused(tmp_path: Path) -> None:
    real = tmp_path / "real.json"
    write_registry(real, "A1")
    link = tmp_path / "corpus" / "slice_v1" / "canaries.public.json"
    link.parent.mkdir(parents=True)
    link.symlink_to(real)
    with pytest.raises(StoreError, match="symlink"):
        load_canary_registry(root=tmp_path, env={})
