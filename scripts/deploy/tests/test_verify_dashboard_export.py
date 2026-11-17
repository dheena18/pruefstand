"""scripts/deploy/verify_dashboard_export.py (T8.5 S3): the checks of deploy.yml's fetch-data."""

import hashlib
import json
from pathlib import Path

import pytest
from deploy.verify_dashboard_export import main, verify

from pruefstand.core.models import dashboard

CHUNK = (
    "Die Kündigungsfrist beträgt vier Wochen zum Fünfzehnten oder zum Ende eines Kalendermonats."
)


def _seal(root: Path) -> None:
    files = {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file() and p.name != "manifest.json" and ".git" not in p.parts
    }
    (root / "manifest.json").write_text(json.dumps({"schema_version": "1", "files": files}))


def _tree(root: Path, runs: int = 2, with_cases: int = 1) -> Path:
    ids = [f"20261103T12000{i}-aaaaa{i}" for i in range(runs)]
    (root / "runs").mkdir(parents=True)
    (root / "runs" / "index.json").write_text(
        json.dumps({"schema_version": "1", "runs": [{"run_id": i} for i in ids]})
    )
    for n, run_id in enumerate(ids):
        (root / "runs" / run_id).mkdir()
        (root / "runs" / run_id / "run.json").write_text(
            json.dumps({"run_id": run_id, "infra_error": None})
        )
        if n < with_cases:
            (root / "cases" / run_id).mkdir(parents=True)
            (root / "cases" / run_id / "0.json").write_text('{"cases": []}')
            (root / "runs" / run_id / "report.html").write_text("<html>ok</html>")
    _seal(root)
    return root


def test_a_good_tree_is_ok(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _tree(tmp_path)
    assert verify(root) == []
    assert main([str(root)]) == 0
    assert "ok (" in capsys.readouterr().out


def test_one_changed_byte_names_the_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _tree(tmp_path)
    target = root / "cases" / sorted(p.name for p in (root / "cases").iterdir())[0] / "0.json"
    target.write_text('{"cases": [ ]}')
    assert main([str(root)]) == 1
    assert "0.json: SHA-256 differs" in capsys.readouterr().err


def test_a_file_missing_from_the_manifest_and_a_listed_file_that_is_gone(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    (root / "extra.json").write_text("{}")
    next((root / "runs").rglob("report.html")).unlink()
    findings = verify(root)
    assert "extra.json: not listed in manifest.json" in findings
    assert any(f.endswith("report.html: listed in manifest.json but missing") for f in findings)


@pytest.mark.parametrize("name", ["runs/x/report.html", "cases/x/0.json", "labels.json"])
def test_canary_in_any_file_including_report_html_fails(tmp_path: Path, name: str) -> None:
    root = _tree(tmp_path)
    target = root / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("hello CANARY-9f3a12 world")
    _seal(root)
    assert f"{name}: contains 'CANARY-'" in verify(root)


def test_a_raw_chunk_text_from_the_fixture_run_fails(tmp_path: Path) -> None:
    root = _tree(tmp_path / "tree")
    (root / "runs" / "leak.html").write_text(f"<p>{CHUNK}</p>")
    _seal(root)
    source = tmp_path / "chunks.jsonl"
    source.write_text(
        json.dumps({"chunk_id": "c", "text": CHUNK}) + "\n" + json.dumps({"text": "kurz"}) + "\n"
    )
    assert main([str(root), "--chunk-texts", str(source)]) == 1
    assert "runs/leak.html: contains raw chunk text" in verify(root, [CHUNK])
    assert verify(root, []) == []


def test_the_size_caps_come_from_the_shared_constants(tmp_path: Path) -> None:
    assert (dashboard.MAX_INDEX_RUNS, dashboard.MAX_CASE_RUNS) == (200, 20)
    root = _tree(tmp_path / "a", runs=dashboard.MAX_INDEX_RUNS + 1, with_cases=0)
    assert any("201 runs, more than 200" in f for f in verify(root))
    exact = _tree(tmp_path / "b", runs=dashboard.MAX_INDEX_RUNS, with_cases=dashboard.MAX_CASE_RUNS)
    assert verify(exact) == []
    over = _tree(tmp_path / "c", runs=30, with_cases=dashboard.MAX_CASE_RUNS + 1)
    assert any("21 runs, more than 20" in f for f in verify(over))


def test_an_unsanitised_infra_error_fails(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    run_json = next((root / "runs").rglob("run.json"))
    run_json.write_text(json.dumps({"infra_error": "tunnel_down: 10.0.0.5 refused"}))
    _seal(root)
    assert any("infra_error still carries a ':' detail" in f for f in verify(root))
    run_json.write_text(json.dumps({"infra_error": "tunnel_down"}))
    _seal(root)
    assert verify(root) == []


def test_a_tree_without_a_manifest_is_a_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([str(tmp_path)]) == 2
    assert "manifest.json not found" in capsys.readouterr().err


def test_a_broken_manifest_is_a_finding(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    (root / "manifest.json").write_text('{"schema_version": "2", "files": {}}')
    assert any(f.startswith("manifest.json: missing or unreadable") for f in verify(root))
