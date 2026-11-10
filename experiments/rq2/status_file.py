"""Read and write ``judges/data/calibration_status.yaml`` (T5.4 S8/S11, X3.3, W3.8)."""

from pathlib import Path

import yaml

from pruefstand.judges.status import FILE

STATUS_PATH = (
    Path(__file__).resolve().parents[2] / "packages/pruefstand/src/pruefstand/judges/data" / FILE
)
HEADER = (
    "# Written by experiments/rq2/report.py (T5.4). Read by pruefstand.judges.status and\n"
    "# pipeline.fingerprints (epoch = judge_epoch, part of eval_fingerprint). Only a passing\n"
    "# re-calibration (experiments/rq2/recalibrate.py) bumps epoch. passed: false = judged\n"
    "# metrics informational in both tiers (W3.8).\n"
)


def read_document(path: Path = STATUS_PATH) -> dict[str, object]:
    """The status document, ``{}`` when the file does not exist."""
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def write_document(doc: dict[str, object], path: Path = STATUS_PATH) -> None:
    """Write the document with its header (keys in insertion order)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    body = yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=110)
    path.write_text(HEADER + body, encoding="utf-8")


def epoch_of(doc: dict[str, object]) -> int:
    """The document's ``epoch`` (1 when unset: the first calibration starts at 1)."""
    value = doc.get("epoch")
    return value if isinstance(value, int) and not isinstance(value, bool) else 1
