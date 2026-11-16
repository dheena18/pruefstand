"""Helpers of the ``baseline promote`` gate-guard tests (D881, D1120)."""

from pathlib import Path
from typing import Any

from testsupport.builders import fixture_f0, make_record, make_run
from testsupport.pipeline_support import config_file, mini_config
from testsupport.report_builders import gate_report
from testsupport.store_support import FP
from typer.testing import CliRunner, Result

from pruefstand.cli import app
from pruefstand.core.config import BaselineStoreConfig
from pruefstand.core.enums import GateStatus
from pruefstand.core.models.run import RunArtifacts
from pruefstand.report.json_report import write_gate_json
from pruefstand.store.artifacts import ArtifactStore
from pruefstand.store.baseline_index import REFS
from pruefstand.store.baselines_local import LocalDirBaselineStore

RUN = "20261102T220001-bbbbbb"
OTHER = "20261102T220009-cccccc"


def stored(
    tmp_path: Path,
    edits: dict[str, dict[int, float]] | None = None,
    drop: tuple[str, ...] = (),
    run_id: str = RUN,
) -> Path:
    cases, values = fixture_f0()
    values = {m: v for m, v in values.items() if m != "faithfulness" and m not in drop}
    for metric, change in (edits or {}).items():
        for index, value in change.items():
            values[metric][index] = value
    records = [make_record(c) for c in cases]
    run = make_run(run_id, cases, values, records=records, eval_fingerprint=FP)
    root = tmp_path / "runs"
    return ArtifactStore(root).write_run(RunArtifacts(results=run, root=root / run_id))


def write_gate(
    run: Path, status: GateStatus = GateStatus.PASS, against: str | None = None, **changes: Any
) -> None:
    """``gate.json`` of ``run``; ``against`` None = the first-promote report (``no_baseline``)."""
    binding = {"baseline_run_id": against, "no_baseline": against is None}
    changes = {"hard_fails": (), "eval_fingerprint": FP, **binding, **changes}
    report = gate_report(candidate_run_id=run.name, status=status, **changes)
    write_gate_json(report, run / "gate.json")


def promote(cli: CliRunner, tmp_path: Path, run: Path, *extra: str, ref: str = "main") -> Result:
    store = BaselineStoreConfig(type="local_dir", path=tmp_path / "store")
    cfg = config_file(tmp_path / "cfg.yaml", mini_config(baseline_store=store))
    args = ["baseline", "promote", "--run", str(run), "--ref", ref, "--config", str(cfg)]
    if "--allow-failed-gate" in extra and "--reason" not in extra:
        extra = (*extra, "--reason", "owner accepted it in a test")  # required since D1123
    return cli.invoke(app, [*args, *extra])


def promoted(tmp_path: Path, run_id: str = RUN) -> bool:
    current = LocalDirBaselineStore(tmp_path / "store").get(FP, "main")
    return current is not None and current.results.manifest.run_id == run_id


def promote_store_test(cli: CliRunner, run_dir: Path, ref: str, cfg: Path, store: Path) -> Result:
    """``baseline promote`` for store tests: a PASS gate.json bound to the stored baseline (D1120).

    The unverifiable leak checks of the two-metric synthetic runs are waived with a reason (D1123).
    """
    if run_dir.is_dir():
        manifest = ArtifactStore(run_dir.parent).read_run(run_dir).results.manifest
        current = None
        if not ref.startswith("release-") and ref in REFS:
            current = LocalDirBaselineStore(store).get(manifest.eval_fingerprint, ref)
        against = None if current is None else current.results.manifest.run_id
        report = gate_report(
            status=GateStatus.PASS,
            hard_fails=(),
            candidate_run_id=run_dir.name,
            eval_fingerprint=manifest.eval_fingerprint,
            baseline_run_id=against,
            no_baseline=against is None,
        )
        write_gate_json(report, run_dir / "gate.json")
    args = ["baseline", "promote", "--run", str(run_dir), "--ref", ref, "--config", str(cfg)]
    return cli.invoke(app, [*args, "--allow-failed-gate", "--reason", "store tests"])
