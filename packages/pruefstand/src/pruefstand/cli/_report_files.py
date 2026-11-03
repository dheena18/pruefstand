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


def evidence_json(
    run: Path,
    report: GateReport,
    gate_raw: bytes,
    pair: tuple[RunManifest | None, RunManifest],
    config: Path,
) -> str:
    """Return ``evidence.json`` for ``run``: the record with file hashes and the thresholds.

    Raises:
        ConfigError: The config cannot be loaded, or its hash differs from the run's
            ``config_hash`` (the thresholds would not be the ones the run was made with).
    """
    base, cand = pair
    cfg = load_config(config)
    if stable_hash(cfg) != cand.config_hash:
        msg = f"{config} is not the config of run {cand.run_id} (config hash differs)"
        raise ConfigError(msg)
    record = build_evidence_record(report, base, cand, None)
    update: dict[str, object] = {
        "thresholds": cfg.gate,
        "gate_json_sha256": hashlib.sha256(gate_raw).hexdigest(),
        "candidate": record.candidate.model_copy(
            update={"run_json_sha256": sha256_file(run / RUN_FILE)}
        ),
    }
    if record.baseline is not None and report.baseline_run_id is not None:
        base_hash = sha256_file(run.parent / report.baseline_run_id / RUN_FILE)
        update["baseline"] = record.baseline.model_copy(update={"run_json_sha256": base_hash})
    return dump_record(record.model_copy(update=update))


def dump_record(record: EvidenceRecord) -> str:
    """Return the record as sorted-key, 2-space JSON with a trailing newline."""
    data = record.model_dump(mode="json")
    return json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
