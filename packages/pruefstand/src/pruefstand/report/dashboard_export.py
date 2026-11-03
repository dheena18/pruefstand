"""``export_dashboard``: run directories in, the published ``data/`` tree out (T8.1, ui-spec §2.3).

Every run is sanitised first (``sanitise_run``: no chunk text, canaries masked, canary cases
dropped); nothing unsanitised reaches the output. Hard-fail evidence in ``gate.json`` is masked
and cleaned too (D542). The export only reshapes: no field is computed, no metric is re-scored.

Size cap (N5.1, D259): the newest ``MAX_INDEX_RUNS`` runs are listed; ``cases/`` and
``report.html`` are written for the newest ``MAX_CASE_RUNS`` of them only.
"""

import hashlib
import json
import re
import secrets
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ValidationError

from pruefstand.core.errors import StoreError
from pruefstand.core.logging import get_logger
from pruefstand.core.models.attacks import CanaryRegistry
from pruefstand.core.models.dashboard import (
    MAX_CASE_RUNS,
    MAX_INDEX_RUNS,
    DashboardRunIndex,
)
from pruefstand.core.models.gate import GateReport, HardFailFinding
from pruefstand.core.models.run import RunArtifacts
from pruefstand.report._dashboard_rows import case_shards, failing_ids, index_entry, slice_rows
from pruefstand.report._html_text import clean
from pruefstand.report.html import render_html
from pruefstand.report.labels import labels_document
from pruefstand.store.artifacts import ArtifactStore
from pruefstand.store.sanitise import REDACTED, sanitise_run, text_masker

__all__ = ["MAX_CASE_RUNS", "MAX_INDEX_RUNS", "dumps", "export_dashboard"]

_log = get_logger(__name__)
MAX_GATE_BYTES = 8 * 1024 * 1024
_EVIDENCE_LIMIT = 199  # HardFailFinding.evidence allows 200 characters; ``clean`` adds an ellipsis
_CANARY = re.compile(rb"canary-", re.IGNORECASE)


@dataclass(frozen=True)
class _Source:
    raw: RunArtifacts
    gate: GateReport | None


def dumps(document: BaseModel | dict[str, object]) -> str:
    """The one JSON format of the export: sorted keys, 2-space indent, UTF-8, trailing newline."""
    data = document.model_dump(mode="json") if isinstance(document, BaseModel) else document
    return json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def _read_gate(directory: Path) -> GateReport | None:
    path = directory / "gate.json"
    if not path.is_file():
        return None
    if path.stat().st_size > MAX_GATE_BYTES:
        msg = f"{path.name} of {directory.name} is larger than {MAX_GATE_BYTES} bytes"
        raise StoreError(msg)
    try:
        return GateReport.model_validate_json(path.read_bytes())
    except ValidationError as exc:
        msg = f"{directory.name}/gate.json is not a valid gate report ({len(exc.errors())} errors)"
        raise StoreError(msg) from exc


def _load(runs_dir: Path) -> list[_Source]:
    """Every readable run below ``runs_dir``; an invalid one is skipped with a warning."""
    if not runs_dir.is_dir():
        msg = f"--runs {runs_dir} is not a directory"
        raise StoreError(msg)
    store = ArtifactStore(runs_dir)
    found: list[_Source] = []
    for directory in sorted(runs_dir.iterdir()):
        if directory.name.startswith(".") or not (directory / "run.json").is_file():
            continue
        try:
            found.append(_Source(store.read_run(directory), _read_gate(directory)))
        except StoreError as exc:
            _log.warning("dashboard_run_skipped", directory=directory.name, error=str(exc)[:200])
    found.sort(key=lambda s: s.raw.results.manifest.run_id)
    found.sort(key=lambda s: s.raw.results.manifest.created_at, reverse=True)
    return found


def _clean_gate(
    gate: GateReport, mask: Callable[[str], str], dropped: frozenset[str]
) -> GateReport:
    """Mask and clean hard-fail evidence; a finding on a dropped (canary) case loses its ids."""
    findings: list[HardFailFinding] = []
    for h in gate.hard_fails:
        if h.case_id in dropped:
            findings.append(h.model_copy(update={"case_id": REDACTED, "evidence": REDACTED}))
        else:
            evidence = clean(mask(h.evidence), _EVIDENCE_LIMIT)
            findings.append(h.model_copy(update={"evidence": evidence}))
    top = tuple(c for c in gate.top_failing_cases if c not in dropped)
    return gate.model_copy(update={"hard_fails": tuple(findings), "top_failing_cases": top})


@dataclass(frozen=True)
class _Clean:
    run: RunArtifacts
    gate: GateReport | None


def _sanitise(source: _Source, canaries: CanaryRegistry) -> _Clean:
    clean_run = sanitise_run(source.raw, canaries)
    if source.gate is None:
        return _Clean(clean_run, None)
    kept = {s.case.id for s in clean_run.results.values}
    dropped = frozenset(s.case.id for s in source.raw.results.values if s.case.id not in kept)
    mask = text_masker(source.raw, canaries)
    return _Clean(clean_run, _clean_gate(source.gate, mask, dropped))


def _run_files(item: _Clean, base: _Clean | None, *, with_cases: bool) -> dict[str, str]:
    """The files of one run, by path below the export root."""
    rid = item.run.results.manifest.run_id
    files = {f"runs/{rid}/run.json": dumps(item.run.results.manifest)}
    if item.gate is not None:
        files[f"runs/{rid}/gate.json"] = dumps(item.gate)
        files[f"runs/{rid}/slices.json"] = dumps(slice_rows(item.gate))
    if with_cases:
        for shard in case_shards(item.run.results, failing_ids(item.gate)):
            files[f"cases/{rid}/{shard.shard}.json"] = dumps(shard)
        if item.gate is not None:
            base_results = None if base is None else base.run.results
            files[f"runs/{rid}/report.html"] = render_html(
                item.gate, base_results, item.run.results
            )
    return files


def _refuse_canaries(files: dict[str, str]) -> None:
    for name, text in files.items():
        if _CANARY.search(text.encode("utf-8")):
            msg = f"refusing to export: {name} still contains 'CANARY-' (unknown canary?)"
            raise StoreError(msg)


def _manifest(files: dict[str, str]) -> str:
    sums = {n: hashlib.sha256(t.encode("utf-8")).hexdigest() for n, t in sorted(files.items())}
    return dumps({"schema_version": "1", "files": sums})


def export_dashboard(runs_dir: Path, out: Path, canaries: CanaryRegistry) -> DashboardRunIndex:
    """Write the dashboard data tree of the runs below ``runs_dir`` into the new directory ``out``.

    Layout (ui-spec §2.3): ``runs/index.json``, ``runs/<id>/{run,gate,slices}.json``,
    ``runs/<id>/report.html`` and ``cases/<id>/<shard>.json`` (the last two for the newest
    ``MAX_CASE_RUNS`` runs, report only with a gate), ``labels.json`` and ``manifest.json``.
    The tree is written to a hidden sibling and renamed, so nothing is left behind on failure.

    Args:
        runs_dir: Directory with ``<run_id>/`` run directories (optional ``gate.json``).
        out: A directory that does not exist yet (an empty one is replaced).
        canaries: The canary registry; an empty one is refused by ``sanitise_run``.

    Returns:
        The written index.

    Raises:
        StoreError: ``runs_dir`` is no directory, ``out`` is not empty, the registry is empty, a
            file would contain ``CANARY-``, or a write failed.
    """
    if out.is_symlink() or (out.exists() and (not out.is_dir() or any(out.iterdir()))):
        msg = f"export directory {out} exists and is not empty; choose a new one"
        raise StoreError(msg)
    chosen = _load(runs_dir)[:MAX_INDEX_RUNS]
    by_id = {s.raw.results.manifest.run_id: s for s in chosen}
    files: dict[str, str] = {}
    entries = []
    for position, source in enumerate(chosen):
        item = _sanitise(source, canaries)
        wanted = None if item.gate is None else item.gate.baseline_run_id
        base = None
        if wanted is not None and wanted in by_id and wanted != item.run.results.manifest.run_id:
            base = _sanitise(by_id[wanted], canaries)
        files.update(_run_files(item, base, with_cases=position < MAX_CASE_RUNS))
        entries.append(index_entry(item.run.results.manifest, item.gate))
    index = DashboardRunIndex(schema_version="1", runs=tuple(entries))
    files["runs/index.json"] = dumps(index)
    files["labels.json"] = dumps(labels_document())
    _refuse_canaries(files)
    files["manifest.json"] = _manifest(files)
    _write(out, files)
    return index


def _write(out: Path, files: dict[str, str]) -> None:
    tmp = out.parent / f".{out.name}.{secrets.token_hex(4)}.tmp"
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        for name, text in files.items():
            target = tmp / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8", newline="\n")
        if out.is_dir():
            out.rmdir()
        tmp.rename(out)
    except OSError as exc:
        shutil.rmtree(tmp, ignore_errors=True)
        msg = f"cannot write the dashboard export {out}: {exc}"
        raise StoreError(msg) from exc
