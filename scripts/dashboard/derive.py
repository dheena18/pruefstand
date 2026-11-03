"""Raw-level fixture derivations for the dashboard (T8.1, ui-spec §14.1, Y7.3, N6.5).

Writes three derived run directories next to the real tier-1 runs of the raw fixtures,
always through real Prüfstand code (``ArtifactStore``, ``run_gate``, ``gate_from_store``):

* ``F-PARTIAL``: the ``F-T1`` run truncated to its first 5 cases, ``complete=false``,
  ``stop_reason="budget_exceeded"``, no ``gate.json``;
* ``F-NO-BASELINE``: a copy of ``F-T1`` gated through the ``--from-store`` code path
  (``gate_from_store``) against an **empty** ``local_dir`` store, which writes the real
  ``no_baseline`` ``gate.json`` (the ``gate`` CLI has no ``--config``-less store choice, UI13-14);
* ``F-JUDGE-SKIPPED``: a copy of ``F-T1`` with ``judge_mode="skipped"``, ``judged_cases=0`` and the
  judged metric values removed, re-gated against ``F-BASE`` (``run_gate``).

Run ids are deterministic (source id + derivation name), so a second run is byte-identical. The
script reads and writes only inside ``--raw`` (temporary files too); ``roles.json`` names the runs.
Usage: ``uv run python scripts/dashboard/derive.py [--partial] [--no-baseline] [--judge-skipped]
[--raw <dir>]`` (no flag derives all three).
"""

import argparse
import hashlib
import json
import shutil
import sys
from collections import Counter
from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path

import polars as pl

from pruefstand.core.config import PruefstandConfig
from pruefstand.core.config.gate import JUDGED_METRICS
from pruefstand.core.config.run import BaselineStoreConfig
from pruefstand.core.config_loader import load_config
from pruefstand.core.enums import MetricStatus
from pruefstand.core.ids import RunId
from pruefstand.core.models.run import RunArtifacts, RunManifest, RunResults, ScoredCase
from pruefstand.pipeline.gate import gate_from_store, run_gate
from pruefstand.store.artifacts import ArtifactStore

DEFAULT_RAW = Path("apps/dashboard/fixtures/raw")
ROLES_FILE = "roles.json"
KEEP_CASES = 5
OFFSETS = {"partial": 1, "no-baseline": 2, "judge-skipped": 3}  # minutes after the source run
NAMES = {
    "partial": "F-PARTIAL",
    "no-baseline": "F-NO-BASELINE",
    "judge-skipped": "F-JUDGE-SKIPPED",
}
_COUNTED = ("ok", "error", "cached", "retrieve", "not_applicable")


def derived_id(source: RunManifest, name: str) -> RunId:
    """The deterministic run id of a derivation: shifted timestamp, hash of source id and name.

    Args:
        source: Manifest of the run the derivation starts from.
        name: ``partial``, ``no-baseline`` or ``judge-skipped``.

    Returns:
        ``<UTC yyyymmddTHHMMSS>-<6 hex>`` (the ``RunId`` format of ``new_run_id``).

    Example:
        >>> from datetime import datetime, UTC
        >>> shifted = datetime(2026, 11, 3, 11, 20, tzinfo=UTC) + timedelta(minutes=1)
        >>> f"{shifted:%Y%m%dT%H%M%S}"
        '20261103T112100'
    """
    stamp = source.created_at + timedelta(minutes=OFFSETS[name])
    digest = hashlib.sha256(f"{source.run_id}|{name}".encode()).hexdigest()[:6]
    return RunId(f"{stamp:%Y%m%dT%H%M%S}-{digest}")


def _roles(raw: Path) -> tuple[dict[str, str], Path]:
    document = json.loads((raw / ROLES_FILE).read_text(encoding="utf-8"))
    return dict(document["roles"]), raw / str(document["config"])


def _counts(values: Sequence[ScoredCase], records_error: Sequence[bool]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    counter["ok"] = sum(1 for failed in records_error if not failed)
    counter["error"] = sum(records_error)
    counter["not_applicable"] = sum(
        1 for s in values for v in s.values if v.status is MetricStatus.NOT_APPLICABLE
    )
    return {k: counter[k] for k in _COUNTED if counter[k]}


def _write(raw: Path, results: RunResults, llm_calls: pl.DataFrame | None) -> Path:
    target = raw / results.manifest.run_id
    if target.exists():  # derived runs are regenerated, never appended to
        shutil.rmtree(target)
    return ArtifactStore(raw).write_run(
        RunArtifacts(results=results, root=target), llm_calls=llm_calls
    )


def _llm_calls(source: Path, keep: set[str] | None) -> pl.DataFrame | None:
    path = source / "llm_calls.parquet"
    if not path.is_file():
        return None
    frame = pl.read_parquet(path)
    if keep is not None and "case_id" in frame.columns:
        frame = frame.filter(pl.col("case_id").is_in(sorted(keep)))
    return frame


def _read(raw: Path, run_id: str) -> RunResults:
    return ArtifactStore(raw).read_run(raw / run_id).results


def derive_partial(raw: Path, source_id: str) -> Path:
    """``F-PARTIAL``: the first 5 cases of the source, incomplete, no ``gate.json``."""
    source = _read(raw, source_id)
    values = source.values[:KEEP_CASES]
    keep: set[str] = {str(s.case.id) for s in values}
    records = tuple(r for r in source.records if r.case_id in keep)
    counts = _counts(values, [r.error is not None for r in records])
    manifest = source.manifest.model_copy(
        update={
            "run_id": derived_id(source.manifest, "partial"),
            "created_at": source.manifest.created_at + timedelta(minutes=OFFSETS["partial"]),
            "n_cases": len(values),
            "complete": False,
            "stop_reason": "budget_exceeded",
            "counts": counts,
            "artifact_sha256": {},
        }
    )
    results = RunResults(manifest=manifest, records=records, values=values)
    return _write(raw, results, _llm_calls(raw / source_id, keep))


def _copy_of(raw: Path, source_id: str, name: str, **update: object) -> RunResults:
    source = _read(raw, source_id)
    manifest = source.manifest.model_copy(
        update={
            "run_id": derived_id(source.manifest, name),
            "created_at": source.manifest.created_at + timedelta(minutes=OFFSETS[name]),
            "artifact_sha256": {},
            **update,
        }
    )
    return RunResults(manifest=manifest, records=source.records, values=source.values)


def derive_no_baseline(raw: Path, source_id: str, cfg: PruefstandConfig) -> Path:
    """``F-NO-BASELINE``: a copy gated by ``gate_from_store`` against an empty ``local_dir`` store.

    The store is an empty directory inside ``raw`` (removed afterwards); no data root is read.
    """
    results = _copy_of(raw, source_id, "no-baseline")
    target = _write(raw, results, _llm_calls(raw / source_id, None))
    empty = raw / f".derive-empty-{results.manifest.run_id}"
    empty.mkdir()
    try:
        store = BaselineStoreConfig(type="local_dir", path=empty, data_root=empty)
        gate_from_store(target, cfg.model_copy(update={"baseline_store": store}), ref="main")
    finally:
        shutil.rmtree(empty, ignore_errors=True)
    return target


def derive_judge_skipped(raw: Path, source_id: str, base_id: str, cfg: PruefstandConfig) -> Path:
    """``F-JUDGE-SKIPPED``: judged values dropped, judge skipped, re-gated vs ``F-BASE``."""
    source = _read(raw, source_id)
    values = tuple(
        s.model_copy(
            update={"values": tuple(v for v in s.values if v.metric not in JUDGED_METRICS)}
        )
        for s in source.values
    )
    counts = {k: n for k, n in source.manifest.counts.items() if not k.startswith("judge_")}
    manifest = source.manifest.model_copy(
        update={
            "run_id": derived_id(source.manifest, "judge-skipped"),
            "created_at": source.manifest.created_at + timedelta(minutes=OFFSETS["judge-skipped"]),
            "judge_mode": "skipped",
            "judged_cases": 0,
            "judge_models": {},
            "judge_prompt_versions": {},
            "judge_fallback": False,
            "judge_degraded": False,
            "judge_drift": False,
            "counts": counts,
            "artifact_sha256": {},
        }
    )
    results = RunResults(manifest=manifest, records=source.records, values=values)
    target = _write(raw, results, _llm_calls(raw / source_id, None))
    run_gate(target, raw / base_id, cfg)
    return target


def main(argv: Sequence[str] | None = None) -> int:
    """Derive the requested fixtures (all three without a flag); print the written run ids."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n", maxsplit=1)[0])
    parser.add_argument("--partial", action="store_true", help="F-PARTIAL only")
    parser.add_argument("--no-baseline", action="store_true", help="F-NO-BASELINE only")
    parser.add_argument("--judge-skipped", action="store_true", help="F-JUDGE-SKIPPED only")
    parser.add_argument("--raw", type=Path, default=DEFAULT_RAW, help="raw run directory")
    args = parser.parse_args(argv)
    chosen = {
        "partial": args.partial,
        "no-baseline": args.no_baseline,
        "judge-skipped": args.judge_skipped,
    }
    wanted = [n for n, on in chosen.items() if on] or list(chosen)
    raw: Path = args.raw
    roles, config_path = _roles(raw)
    cfg = load_config(config_path)
    for name in wanted:
        if name == "partial":
            written = derive_partial(raw, roles["F-T1"])
        elif name == "no-baseline":
            written = derive_no_baseline(raw, roles["F-T1"], cfg)
        else:
            written = derive_judge_skipped(raw, roles["F-T1"], roles["F-BASE"], cfg)
        sys.stdout.write(f"{NAMES[name]} {written.name}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
