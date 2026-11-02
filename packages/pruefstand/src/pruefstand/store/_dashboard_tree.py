"""Merge-and-prune of the published dashboard-data tree (R13 P5.1, D300).

After a run's files were added, ``rewrite_tree`` rebuilds ``runs/index.json`` from every
``runs/*/run.json`` present (never from VM run directories), keeps the newest ``MAX_INDEX_RUNS``
runs and the case shards and ``report.html`` only for the newest ``MAX_CASE_RUNS``, and rewrites
``manifest.json`` (SHA-256 per file) so pruned files disappear from the tree.
"""

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from pruefstand.core.errors import StoreError
from pruefstand.core.models.dashboard import MAX_CASE_RUNS, MAX_INDEX_RUNS
from pruefstand.core.models.run import RunManifest
from pruefstand.store._run_files import read_bounded

MAX_JSON_BYTES = 4 * 1024 * 1024
_SKIP = ".git"


def refuse_symlinks(root: Path) -> None:
    """Raise when anything below ``root`` (outside ``.git``) is a symlink.

    Raises:
        StoreError: A symlink was found.
    """
    for path in root.rglob("*"):
        if _SKIP in path.relative_to(root).parts:
            continue
        if path.is_symlink():
            msg = f"{path.relative_to(root)} is a symlink; the published tree holds regular files"
            raise StoreError(msg)


def _gate_fields(directory: Path) -> dict[str, Any]:
    fields: dict[str, Any] = {"status": None, "baseline_run_id": None, "no_baseline": False}
    path = directory / "gate.json"
    if not path.is_file():
        return fields
    try:
        gate = json.loads(read_bounded(path, MAX_JSON_BYTES))
    except (StoreError, ValueError):
        return fields
    if isinstance(gate, dict):
        status, baseline = gate.get("status"), gate.get("baseline_run_id")
        fields["status"] = status if isinstance(status, str) else None
        fields["baseline_run_id"] = baseline if isinstance(baseline, str) else None
        fields["no_baseline"] = gate.get("no_baseline") is True
    return fields


def _row(manifest: RunManifest, directory: Path) -> dict[str, Any]:
    data = manifest.model_dump(mode="json")
    row = {
        name: data[name]
        for name in (
            "run_id", "created_at", "git_ref", "git_sha", "pr_number", "n_cases", "duration_s",
            "complete", "stop_reason", "stack", "workload", "judge_mode", "judge_fallback",
            "judge_degraded", "judge_drift", "block", "judged_subset",
        )
    }  # fmt: skip
    row["cost_usd"] = manifest.cost.usd
    return {**row, **_gate_fields(directory)}


def _runs(root: Path) -> list[tuple[RunManifest, Path]]:
    found: list[tuple[RunManifest, Path]] = []
    runs = root / "runs"
    if not runs.is_dir():
        return found
    for directory in sorted(runs.iterdir()):
        if not directory.is_dir():
            continue
        try:
            manifest = RunManifest.model_validate_json(
                read_bounded(directory / "run.json", MAX_JSON_BYTES)
            )
        except (StoreError, ValidationError):
            shutil.rmtree(directory)
            continue
        if manifest.run_id != directory.name:
            shutil.rmtree(directory)
            continue
        found.append((manifest, directory))
    found.sort(key=lambda item: (item[0].created_at, item[0].run_id), reverse=True)
    return found


def _drop(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def rewrite_tree(
    root: Path, *, max_index: int = MAX_INDEX_RUNS, max_cases: int = MAX_CASE_RUNS
) -> list[dict[str, Any]]:
    """Prune the tree at ``root`` and rewrite ``runs/index.json`` and ``manifest.json``.

    Args:
        root: A checkout of the dashboard-data repository.
        max_index: Runs kept (newest by ``created_at``, then run id).
        max_cases: Runs that keep ``cases/<id>/`` and ``runs/<id>/report.html``.

    Returns:
        The index rows, newest first (copied from ``run.json`` and ``gate.json``).

    Raises:
        StoreError: A symlink is in the tree, or a file cannot be written.
    """
    refuse_symlinks(root)
    runs = _runs(root)
    for manifest, directory in runs[max_index:]:
        _drop(directory)
        _drop(root / "cases" / manifest.run_id)
    kept = runs[:max_index]
    for manifest, directory in kept[max_cases:]:
        _drop(directory / "report.html")
        _drop(root / "cases" / manifest.run_id)
    with_cases = {m.run_id for m, _ in kept[:max_cases]}
    cases = root / "cases"
    if cases.is_dir():
        for entry in cases.iterdir():
            if entry.name not in with_cases:
                _drop(entry)
        if not any(cases.iterdir()):
            cases.rmdir()
    rows = [_row(manifest, directory) for manifest, directory in kept]
    index = {"schema_version": "1", "runs": rows}
    (root / "runs").mkdir(exist_ok=True)
    text = json.dumps(index, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    (root / "runs" / "index.json").write_text(text, encoding="utf-8")
    write_manifest(root)
    return rows


def write_manifest(root: Path) -> None:
    """Write ``manifest.json``: the SHA-256 of every file except ``.git`` and itself."""
    files = {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
        and _SKIP not in path.relative_to(root).parts
        and path.relative_to(root).as_posix() != "manifest.json"
    }
    text = json.dumps({"schema_version": "1", "files": files}, indent=2, sort_keys=True) + "\n"
    (root / "manifest.json").write_text(text, encoding="utf-8")
