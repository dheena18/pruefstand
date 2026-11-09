"""Files behind ``pruefstand report --format html|evidence``: reads, hashes, atomic writes."""

import hashlib
import json
import os
import tempfile
from pathlib import Path

from pruefstand.core.config_loader import load_config
from pruefstand.core.errors import ConfigError
from pruefstand.core.hashing import stable_hash
from pruefstand.core.models.evidence import EvidenceRecord
from pruefstand.core.models.gate import GateReport
from pruefstand.core.models.run import RunManifest
from pruefstand.pipeline._files import read_regular
from pruefstand.report._html_text import masked
from pruefstand.report.evidence import build_evidence_record

HTML_FILE = "report.html"
EVIDENCE_FILE = "evidence.json"
RUN_FILE = "run.json"
_MAX_RUN_BYTES = 64 * 1024 * 1024


def sha256_file(path: Path) -> str | None:
    """Return the SHA-256 of the regular file ``path``, or ``None`` when it cannot be read."""
    try:
        raw = read_regular(path, _MAX_RUN_BYTES)
    except OSError:
        return None
    return hashlib.sha256(raw).hexdigest() if len(raw) <= _MAX_RUN_BYTES else None


def write_atomic(path: Path, text: str) -> None:
    """Write ``text`` (UTF-8, LF) to ``path`` through a temporary file in the same directory."""
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        tmp.chmod(0o644)
        tmp.replace(path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _read_manifest(path: Path) -> tuple[RunManifest, str] | None:
    """Return the manifest parsed from the bytes of ``path`` and the SHA-256 of those bytes."""
    try:
        raw = read_regular(path, _MAX_RUN_BYTES)
        return RunManifest.model_validate_json(raw), hashlib.sha256(raw).hexdigest()
    except (OSError, ValueError):
        return None


def baseline_dir(run: Path, report: GateReport) -> Path | None:
    """Return the baseline run directory named by ``gate.json`` (a sibling of ``run``), or None.

    ``baseline_run_id`` comes from a file inside the run directory, so it must be one plain
    directory name: no separator, no ``.`` / ``..``, no NUL.

    Raises:
        ConfigError: The id is not a plain directory name.
    """
    name = report.baseline_run_id
    if name is None:
        return None
    plain = bool(name) and name not in {".", ".."} and Path(name).name == name
    if not plain or "\\" in name or "\0" in name:
        msg = f"{run / 'gate.json'}: baseline_run_id {name[:60]!r} is not a plain run id"
        raise ConfigError(msg)
    return run.parent / name


def check_gate_matches_run(run: Path, report: GateReport) -> None:
    """Refuse a ``gate.json`` that was written for another run than the one next to it.

    Raises:
        ConfigError: ``candidate_run_id`` differs from the ``run_id`` in ``run.json`` (an
            unreadable ``run.json`` is reported by the command that reads the run).
    """
    mine = _read_manifest(run / RUN_FILE)
    if mine is not None and mine[0].run_id != report.candidate_run_id:
        msg = (
            f"{run / 'gate.json'} is the gate result of run {report.candidate_run_id[:60]}, "
            f"not of {mine[0].run_id[:60]}"
        )
        raise ConfigError(msg)


def mask_strings(value: object) -> object:
    """Return ``value`` (JSON data) with the detector's canary mask applied to every string."""
    if isinstance(value, str):
        return masked(value)
    if isinstance(value, list):
        return [mask_strings(v) for v in value]
    if isinstance(value, dict):
        return {k: mask_strings(v) for k, v in value.items()}
    return value


def evidence_json(run: Path, report: GateReport, gate_raw: bytes, config: Path) -> str:
    """Return ``evidence.json`` for ``run``: the record with file hashes and the thresholds.

    Raises:
        ConfigError: The config cannot be loaded, or its hash differs from the run's
            ``config_hash`` (the thresholds would not be the ones the run was made with).
    """
    mine = _read_manifest(run / RUN_FILE)
    if mine is None:
        msg = f"{run / RUN_FILE} cannot be read"
        raise ConfigError(msg)
    cand, cand_hash = mine
    theirs = None
    if report.baseline_run_id is not None:
        directory = baseline_dir(run, report)
        theirs = None if directory is None else _read_manifest(directory / RUN_FILE)
    base = None if theirs is None else theirs[0]
    cfg = load_config(config)
    if stable_hash(cfg) != cand.config_hash:
        msg = f"{config} is not the config of run {cand.run_id} (config hash differs)"
        raise ConfigError(msg)
    record = build_evidence_record(report, base, cand, None)
    update: dict[str, object] = {
        "thresholds": cfg.gate,
        "gate_json_sha256": hashlib.sha256(gate_raw).hexdigest(),
        "candidate": record.candidate.model_copy(update={"run_json_sha256": cand_hash}),
    }
    if record.baseline is not None and theirs is not None:
        update["baseline"] = record.baseline.model_copy(update={"run_json_sha256": theirs[1]})
    return dump_record(record.model_copy(update=update))


def dump_record(record: EvidenceRecord) -> str:
    """Return the record as sorted-key, 2-space JSON with a trailing newline."""
    data = mask_strings(record.model_dump(mode="json"))
    return json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
