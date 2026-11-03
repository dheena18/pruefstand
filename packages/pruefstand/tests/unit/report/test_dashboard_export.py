"""``export_dashboard`` on the real tier-1 runs under ``apps/dashboard/fixtures/raw`` (T8.1).

The raw runs are real ``live-e2e`` run directories (public slice only) plus the ``derive.py`` runs.
"""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import BaseModel
from testsupport.dashboard_export_support import RAW, all_text, clone, copy_runs, registry, roles

from pruefstand.core.errors import StoreError
from pruefstand.core.models import dashboard as dashboard_models
from pruefstand.core.models.dashboard import (
    MAX_CASE_RUNS,
    MAX_INDEX_RUNS,
    DashboardCases,
    DashboardRunIndex,
    DashboardSlices,
    LabelsDocument,
)
from pruefstand.core.models.gate import GateReport
from pruefstand.core.models.run import RunManifest
from pruefstand.report import dashboard_export
from pruefstand.report.dashboard_export import export_dashboard
from pruefstand.report.labels import labels_document
from pruefstand.store.artifacts import ArtifactStore


@pytest.fixture(scope="module")
def exported(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("export") / "data"
    export_dashboard(RAW, out, registry())
    return out


def _raw_runs() -> dict[str, tuple[RunManifest, GateReport | None]]:
    found: dict[str, tuple[RunManifest, GateReport | None]] = {}
    for directory in sorted(RAW.iterdir()):
        if not (directory / "run.json").is_file():
            continue
        manifest = RunManifest.model_validate_json((directory / "run.json").read_text("utf-8"))
        gate_file = directory / "gate.json"
        gate = (
            GateReport.model_validate_json(gate_file.read_text("utf-8"))
            if gate_file.is_file()
            else None
        )
        found[manifest.run_id] = (manifest, gate)
    return found


def _index(root: Path) -> DashboardRunIndex:
    return DashboardRunIndex.model_validate_json((root / "runs/index.json").read_text("utf-8"))


def test_index_is_sorted_newest_first_with_one_entry_per_run(exported: Path) -> None:
    index = _index(exported)
    raw = _raw_runs()
    assert {e.run_id for e in index.runs} == set(raw)
    stamps = [e.created_at for e in index.runs]
    assert stamps == sorted(stamps, reverse=True)


def test_every_index_field_equals_its_source(exported: Path) -> None:
    raw = _raw_runs()
    for entry in _index(exported).runs:
        manifest, gate = raw[entry.run_id]
        assert entry.created_at == manifest.created_at
        assert (entry.git_ref, entry.git_sha, entry.pr_number) == (
            manifest.git_ref,
            manifest.git_sha,
            manifest.pr_number,
        )
        # n_cases is the sanitised count: canary cases are dropped from the exported run.json too
        exported_run = RunManifest.model_validate_json(
            (exported / "runs" / entry.run_id / "run.json").read_text("utf-8")
        )
        assert entry.n_cases == exported_run.n_cases <= manifest.n_cases
        assert (entry.duration_s, entry.cost_usd) == (manifest.duration_s, manifest.cost.usd)
        assert (entry.complete, entry.stop_reason) == (manifest.complete, manifest.stop_reason)
        assert (entry.stack, entry.workload) == (manifest.stack, manifest.workload)
        assert (entry.judge_mode, entry.judge_fallback) == (
            manifest.judge_mode,
            manifest.judge_fallback,
        )
        assert (entry.judge_degraded, entry.judge_drift) == (
            manifest.judge_degraded,
            manifest.judge_drift,
        )
        assert (entry.block, entry.judged_subset) == (manifest.block, manifest.judged_subset)
        assert entry.status == (None if gate is None else gate.status)
        assert entry.baseline_run_id == (None if gate is None else gate.baseline_run_id)
        assert entry.no_baseline == (False if gate is None else gate.no_baseline)


def test_each_run_has_a_slices_row_per_decision_and_report_and_cases_exactly_when_gated(
    exported: Path,
) -> None:
    raw = _raw_runs()
    for run_id, (_, gate) in raw.items():
        base = exported / "runs" / run_id
        assert (base / "run.json").is_file()
        assert (base / "gate.json").is_file() == (gate is not None)
        assert (base / "slices.json").is_file() == (gate is not None)
        assert (base / "report.html").is_file() == (gate is not None)
        assert (exported / "cases" / run_id / "0.json").is_file()
        if gate is not None:
            slices = DashboardSlices.model_validate_json((base / "slices.json").read_text("utf-8"))
            assert len(slices.rows) == len(gate.decisions) + len(gate.absolute_checks) + len(
                gate.notable_slices
            )


def test_no_baseline_run_exports_a_report_with_baseline_dash(exported: Path) -> None:
    entry = next(e for e in _index(exported).runs if e.no_baseline)
    assert entry.baseline_run_id is None
    html = (exported / "runs" / entry.run_id / "report.html").read_text("utf-8")
    assert 'Baseline: <span class="mono">–</span>' in html


def test_a_baseline_that_is_not_in_the_runs_dir_exports_with_base_none(tmp_path: Path) -> None:
    store = copy_runs(
        [roles()["F-T1"]], tmp_path / "only"
    )  # its gate.json names F-BASE, which is not here
    out = tmp_path / "data"
    export_dashboard(store, out, registry())
    (entry,) = _index(out).runs
    assert entry.baseline_run_id == roles()["F-BASE"]
    assert (out / "runs" / entry.run_id / "report.html").is_file()


def test_shards_labels_and_manifest_validate_and_match(exported: Path) -> None:
    for run_dir in sorted((exported / "cases").iterdir()):
        shards = sorted(run_dir.glob("*.json"))
        for shard in shards:
            doc = DashboardCases.model_validate_json(shard.read_text("utf-8"))
            assert doc.run_id == run_dir.name
            assert doc.shard == int(shard.stem)
            assert doc.n_shards == len(shards)
            assert len(doc.cases) <= 500
    labels = json.loads((exported / "labels.json").read_text("utf-8"))
    assert labels == labels_document().model_dump(mode="json")
    LabelsDocument.model_validate(labels)
    manifest = json.loads((exported / "manifest.json").read_text("utf-8"))
    files = all_text(exported)
    assert set(manifest["files"]) == set(files) - {"manifest.json"}
    for name, digest in manifest["files"].items():
        assert hashlib.sha256(files[name].encode("utf-8")).hexdigest() == digest


def test_report_html_has_no_chunk_text_and_no_canary(exported: Path) -> None:
    for name, text in all_text(exported).items():
        assert "CANARY-" not in text.upper(), name
    reports = list(exported.glob("runs/*/report.html"))
    assert reports


def test_the_leaking_scenario_run_exports_neither_chunk_text_nor_a_canary_token(
    exported: Path,
) -> None:
    run_id = roles()["F-HARD-FAIL"]
    results = ArtifactStore(RAW).read_run(RAW / run_id).results
    texts = {
        c.text
        for r in results.records
        if r.response and r.response.chunks
        for c in r.response.chunks
    }
    tokens = {t for c in registry().canaries for t in (c.token, c.fact, c.forbidden_answer) if t}
    assert texts
    published = all_text(exported)
    for name, body in published.items():
        for chunk in texts:
            if len(chunk) >= 80:
                assert chunk not in body, name
        for token in tokens:
            assert token.casefold() not in body.casefold(), name
    gate = GateReport.model_validate_json(published[f"runs/{run_id}/gate.json"])
    assert gate.hard_fails


def test_hard_fail_evidence_is_masked_and_a_canary_case_loses_its_ids(tmp_path: Path) -> None:
    run_id = roles()["F-HARD-FAIL"]
    store = copy_runs([run_id], tmp_path / "store")
    token = registry().canaries[0].token
    gate_file = store / run_id / "gate.json"
    gate = json.loads(gate_file.read_text("utf-8"))
    gate["hard_fails"][0]["evidence"] = f"answer repeated {token} verbatim"
    gate_file.write_text(json.dumps(gate), encoding="utf-8")
    out = tmp_path / "data"
    export_dashboard(store, out, registry())
    clean = GateReport.model_validate_json((out / "runs" / run_id / "gate.json").read_text("utf-8"))
    assert token not in clean.hard_fails[0].evidence
    assert "redacted" in clean.hard_fails[0].evidence
    assert clean.hard_fails[0].rule == gate["hard_fails"][0]["rule"]


def test_infra_error_kind_is_exported_unchanged(tmp_path: Path) -> None:
    store = tmp_path / "store"
    source = RAW / roles()["F-T1"]
    new = clone(source, store, "20261103T090000-abcdef", datetime(2026, 11, 3, 9, tzinfo=UTC),
                complete=False, stop_reason="aborted", infra_error="tunnel_lost")  # fmt: skip
    (new / "gate.json").unlink(missing_ok=True)
    out = tmp_path / "data"
    export_dashboard(store, out, registry())
    run = RunManifest.model_validate_json((out / "runs" / new.name / "run.json").read_text("utf-8"))
    assert run.infra_error == "tunnel_lost"


def test_size_cap_keeps_the_newest_200_runs_and_cases_for_the_newest_20(tmp_path: Path) -> None:
    store = tmp_path / "store"
    source = RAW / roles()["F-T1"]
    start = datetime(2026, 1, 1, tzinfo=UTC)
    ids = []
    for i in range(205):
        run_id = f"{start + timedelta(minutes=i):%Y%m%dT%H%M%S}-{i:06x}"
        clone(source, store, run_id, start + timedelta(minutes=i))
        ids.append(run_id)
    out = tmp_path / "data"
    index = export_dashboard(store, out, registry())
    newest = sorted(ids, reverse=True)
    assert [e.run_id for e in index.runs] == newest[:MAX_INDEX_RUNS]
    for run_id in newest[:MAX_INDEX_RUNS]:
        assert (out / "runs" / run_id / "run.json").is_file()
        published = run_id in newest[:MAX_CASE_RUNS]
        assert (out / "cases" / run_id).is_dir() == published
        assert (out / "runs" / run_id / "report.html").is_file() == published
    for run_id in newest[MAX_INDEX_RUNS:]:
        assert not (out / "runs" / run_id).exists()
        assert not (out / "cases" / run_id).exists()


def test_the_export_uses_the_shared_size_caps() -> None:
    assert dashboard_export.MAX_INDEX_RUNS is dashboard_models.MAX_INDEX_RUNS
    assert dashboard_export.MAX_CASE_RUNS is dashboard_models.MAX_CASE_RUNS


def test_refuses_a_non_empty_out_an_empty_registry_and_a_missing_runs_dir(tmp_path: Path) -> None:
    out = tmp_path / "data"
    out.mkdir()
    (out / "x").write_text("x", encoding="utf-8")
    with pytest.raises(StoreError, match="not empty"):
        export_dashboard(RAW, out, registry())
    with pytest.raises(StoreError, match="not a directory"):
        export_dashboard(tmp_path / "missing", tmp_path / "o", registry())
    with pytest.raises(StoreError, match="registry is empty"):
        export_dashboard(RAW, tmp_path / "o2", registry().model_copy(update={"canaries": ()}))
    assert not (tmp_path / "o2").exists()


def test_models_reject_unknown_fields() -> None:
    models: list[type[BaseModel]] = [DashboardRunIndex, DashboardSlices, DashboardCases]
    for model in models:
        with pytest.raises(ValueError, match=r"extra|schema_version|Field required"):
            model.model_validate({"unexpected": 1})
