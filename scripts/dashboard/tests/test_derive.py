"""``scripts/dashboard/derive.py``: raw-level fixture derivations via real Prüfstand code (T8.1).

The tests copy one real tier-1 run (and its baseline) of ``apps/dashboard/fixtures/raw`` into
``tmp_path`` and derive from the copy; nothing in the repository is written.
"""

import hashlib
import json
import re
import shutil
from pathlib import Path

import polars as pl
import pytest
from dashboard.derive import ROLES_FILE, derived_id, main

from pruefstand.core.models.gate import GateReport
from pruefstand.core.models.run import RunManifest
from pruefstand.store.artifacts import ArtifactStore

REPO = Path(__file__).resolve().parents[3]
RAW = REPO / "apps" / "dashboard" / "fixtures" / "raw"
RUN_ID = re.compile(r"\d{8}T\d{6}-[0-9a-f]{6}")


@pytest.fixture
def raw(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A raw dir holding F-T1, F-BASE, the config and roles.json; the data root does not exist."""
    monkeypatch.setenv("PRUEFSTAND_DATA_ROOT", str(tmp_path / "does-not-exist"))
    roles = json.loads((RAW / ROLES_FILE).read_text(encoding="utf-8"))
    target = tmp_path / "raw"
    target.mkdir()
    for role in ("F-T1", "F-BASE"):
        shutil.copytree(RAW / roles["roles"][role], target / roles["roles"][role])
    shutil.copy(RAW / roles["config"], target / roles["config"])
    keep = {"config": roles["config"], "roles": {r: roles["roles"][r] for r in ("F-T1", "F-BASE")}}
    (target / ROLES_FILE).write_text(json.dumps(keep), encoding="utf-8")
    return target


def _manifest(raw: Path, name: str) -> RunManifest:
    return RunManifest.model_validate_json((raw / name / "run.json").read_text(encoding="utf-8"))


def _new(raw: Path) -> list[str]:
    """Run directories that are neither F-T1 nor F-BASE: the derived runs."""
    roles = json.loads((raw / ROLES_FILE).read_text(encoding="utf-8"))["roles"]
    known = set(roles.values())
    return sorted(
        p.name
        for p in raw.iterdir()
        if p.is_dir() and p.name not in known and not p.name.startswith(".")
    )


def _tree(path: Path) -> dict[str, str]:
    return {
        p.relative_to(path).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(path.rglob("*"))
        if p.is_file()
    }


def test_partial_is_truncated_incomplete_and_has_no_gate(raw: Path) -> None:
    assert main(["--raw", str(raw), "--partial"]) == 0
    (name,) = _new(raw)
    manifest = _manifest(raw, name)
    assert manifest.complete is False
    assert manifest.stop_reason == "budget_exceeded"
    assert manifest.n_cases == 5
    assert pl.read_parquet(raw / name / "results.parquet")["case_id"].n_unique() == 5
    lines = (raw / name / "responses.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 5
    assert not (raw / name / "gate.json").exists()


def test_no_baseline_goes_through_the_from_store_path(raw: Path, tmp_path: Path) -> None:
    assert main(["--raw", str(raw), "--no-baseline"]) == 0
    (name,) = _new(raw)
    gate = GateReport.model_validate_json((raw / name / "gate.json").read_text(encoding="utf-8"))
    assert gate.no_baseline is True
    assert gate.baseline_run_id is None
    assert gate.candidate_run_id == name
    assert not (tmp_path / "does-not-exist").exists()
    assert [p for p in raw.iterdir() if p.name.startswith(".")] == []  # temp store removed


def test_judge_skipped_drops_judged_values_and_regates_against_the_baseline(raw: Path) -> None:
    roles = json.loads((raw / ROLES_FILE).read_text(encoding="utf-8"))["roles"]
    assert main(["--raw", str(raw), "--judge-skipped"]) == 0
    (name,) = _new(raw)
    manifest = _manifest(raw, name)
    assert manifest.judge_mode == "skipped"
    assert manifest.judged_cases == 0
    assert manifest.judge_models == {}
    results = pl.read_parquet(raw / name / "results.parquet")
    assert not {"faithfulness", "answer_correctness"} & set(results["metric"].to_list())
    gate = GateReport.model_validate_json((raw / name / "gate.json").read_text(encoding="utf-8"))
    assert gate.baseline_run_id == roles["F-BASE"]
    assert gate.no_baseline is False


def test_no_argument_derives_all_three_with_valid_deterministic_ids(raw: Path) -> None:
    roles = json.loads((raw / ROLES_FILE).read_text(encoding="utf-8"))["roles"]
    assert main(["--raw", str(raw)]) == 0
    names = _new(raw)
    assert len(names) == 3
    assert all(RUN_ID.fullmatch(n) for n in names)
    source = _manifest(raw, roles["F-T1"])
    assert set(names) == {
        derived_id(source, n) for n in ("partial", "no-baseline", "judge-skipped")
    }
    for name in names:  # every derived run reads back through the verifying reader
        assert ArtifactStore(raw).read_run(raw / name).results.manifest.run_id == name


def test_running_twice_is_byte_identical_and_touches_nothing_outside_raw(raw: Path) -> None:
    fixtures = REPO / "apps" / "dashboard" / "fixtures"
    outside = _tree(fixtures)
    assert main(["--raw", str(raw)]) == 0
    first = _tree(raw)
    assert main(["--raw", str(raw)]) == 0
    assert _tree(raw) == first
    assert _tree(fixtures) == outside
