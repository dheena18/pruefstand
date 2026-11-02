"""``write_gate_json``: stable, round-trippable ``gate.json``."""

import json
from pathlib import Path

from testsupport.report_builders import decision, gate_report, no_baseline_report

from pruefstand.core.models.gate import GateReport
from pruefstand.report.json_report import write_gate_json


def test_keys_sorted_indent_utf8_trailing_newline(tmp_path: Path) -> None:
    report = gate_report(decisions=(decision(value="Kündigung", dimension="tags"),))
    path = tmp_path / "gate.json"
    write_gate_json(report, path)
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    assert "Kündigung" in text
    assert "\\u00fc" not in text
    assert text.endswith("}\n")
    assert text.startswith('{\n  "')
    data = json.loads(text)
    assert list(data) == sorted(data)
    assert text == json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def test_round_trip_equal(tmp_path: Path) -> None:
    report = gate_report()
    path = tmp_path / "gate.json"
    write_gate_json(report, path)
    assert GateReport.model_validate_json(path.read_text(encoding="utf-8")) == report


def test_no_baseline_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "sub" / "gate.json"
    write_gate_json(no_baseline_report(), path)
    back = GateReport.model_validate_json(path.read_text(encoding="utf-8"))
    assert back.baseline_run_id is None
    assert back.no_baseline is True


def test_overwrite_leaves_no_temp_files(tmp_path: Path) -> None:
    path = tmp_path / "gate.json"
    write_gate_json(gate_report(), path)
    write_gate_json(gate_report(status="warn"), path)
    assert [p.name for p in tmp_path.iterdir()] == ["gate.json"]
    assert json.loads(path.read_text(encoding="utf-8"))["status"] == "warn"
