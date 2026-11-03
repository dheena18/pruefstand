"""Helpers of the dashboard-export tests: the committed raw runs, clones and file walking."""

import json
import shutil
from datetime import datetime
from pathlib import Path

from pruefstand.core.models.attacks import CanaryRegistry
from pruefstand.core.models.gate import GateReport
from pruefstand.core.models.run import RunArtifacts, RunResults
from pruefstand.store.artifacts import ArtifactStore
from pruefstand.store.canary_source import load_canary_registry

REPO = Path(__file__).resolve().parents[4]
RAW = REPO / "apps" / "dashboard" / "fixtures" / "raw"


def roles() -> dict[str, str]:
    """Role (``F-BASE``, ``F-T1``, ``F-HARD-FAIL``, ...) to run id of the committed raw runs."""
    document = json.loads((RAW / "roles.json").read_text(encoding="utf-8"))
    found: dict[str, str] = document["roles"]
    return found


def registry() -> CanaryRegistry:
    """The public canary registry of the slice corpus (no held-out registry)."""
    return load_canary_registry(root=REPO, env={})


def copy_runs(names: list[str], target: Path) -> Path:
    """Copy committed raw run directories into ``target`` (a store root)."""
    target.mkdir(parents=True, exist_ok=True)
    for name in names:
        shutil.copytree(RAW / name, target / name)
    return target


def clone(source: Path, store: Path, run_id: str, created_at: datetime, **update: object) -> Path:
    """A copy of a stored run under a new id and date (its ``gate.json`` follows)."""
    results = ArtifactStore(source.parent).read_run(source).results
    manifest = results.manifest.model_copy(
        update={"run_id": run_id, "created_at": created_at, "artifact_sha256": {}, **update}
    )
    clone_results = RunResults(manifest=manifest, records=results.records, values=results.values)
    target = store / run_id
    ArtifactStore(store).write_run(RunArtifacts(results=clone_results, root=target))
    gate = source / "gate.json"
    if gate.is_file():
        report = GateReport.model_validate_json(gate.read_text(encoding="utf-8"))
        moved = report.model_copy(update={"candidate_run_id": run_id})
        (target / "gate.json").write_text(moved.model_dump_json(indent=2), encoding="utf-8")
    return target


def all_text(root: Path) -> dict[str, str]:
    """Every exported file below ``root`` by relative path."""
    return {
        p.relative_to(root).as_posix(): p.read_text(encoding="utf-8")
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }
