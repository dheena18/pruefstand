"""``gate.json`` writer (interfaces §10): sorted keys, 2-space indent, UTF-8, trailing newline."""

import json
import os
import tempfile
from pathlib import Path

from pruefstand.core.models.gate import GateReport


def write_gate_json(report: GateReport, path: Path) -> None:
    """Write ``report`` to ``path`` so that ``GateReport.model_validate_json`` reads it back equal.

    The file is written to a temporary file in the same directory and renamed, so a reader never
    sees a half-written ``gate.json``. Missing parent directories are created.

    Args:
        report: The gate report.
        path: Target file (overwritten).

    Raises:
        OSError: The directory or file cannot be written.
    """
    text = json.dumps(report.model_dump(mode="json"), sort_keys=True, indent=2, ensure_ascii=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text + "\n")
        tmp.chmod(0o644)
        tmp.replace(path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
