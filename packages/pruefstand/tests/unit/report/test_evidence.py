"""``build_evidence_record`` and the evidence CLI path (T6.4)."""

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from testsupport.report_builders import (
    absolute_row,
    base_manifest,
    decision,
    gate_report,
    info_row,
    manifest,
    no_baseline_report,
    notable_row,
)

from pruefstand.cli._report_files import sha256_file
from pruefstand.core.enums import GateStatus
from pruefstand.core.models.evidence import EvidenceRecord
from pruefstand.core.models.gate import GateReport
from pruefstand.core.schema import export_schemas
from pruefstand.report.evidence import build_evidence_record


def report() -> GateReport:
    return gate_report(
        decisions=(decision(), decision(dimension="tenant", value="kanzlei_mueller")),
        absolute_checks=(absolute_row("injection_success", 0.01),),
        notable_slices=(notable_row("perturbation", "compound_split", -0.18),),
    )


def test_record_carries_decision_fingerprints_and_results() -> None:
    rec = build_evidence_record(report(), base_manifest(), manifest(), "A. Reviewer")
    assert rec.gate_status is GateStatus.FAIL
    assert not rec.no_baseline
    assert rec.reviewer == "A. Reviewer"
    assert rec.eval_fingerprint == "e" * 16
    assert rec.config_hash == "c" * 16
    assert rec.candidate.run_id == "20261102T220000-ab12cd"
    assert rec.candidate.complete
    assert rec.baseline is not None
    assert rec.baseline.git_sha is not None
    assert rec.splits == ("core", "robust_pr")
    assert rec.dataset_name == "pruefstand-de"
    first = rec.results[0]
    assert (first.metric, first.table, first.mean_diff, first.ci_low) == (
        "context_recall",
        "gated",
        -0.07,
        -0.10,
    )
    assert {r.table for r in rec.results} == {"gated", "notable"}
    assert rec.security.hard_fail_count == 1
    assert rec.security.leak_metrics["canary_leak"] == 1
    assert rec.security.injection_success == 0.01
    assert rec.results[-1].table == "notable"


def test_informational_decisions_keep_their_reason() -> None:
    rep = gate_report(
        decisions=(
            info_row("refusal_correct", "refusal_outside_nightly_full", 1.0, 0.9, diff=-0.1),
        )
    )
    rec = build_evidence_record(rep, base_manifest(), manifest(), None)
    assert (rec.results[0].table, rec.results[0].informational_reason) == (
        "informational",
        "refusal_outside_nightly_full",
    )


def test_record_validates_against_the_exported_schema(tmp_path: Path) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    export_schemas(tmp_path)
    schema = json.loads((tmp_path / "evidence_record.schema.json").read_text(encoding="utf-8"))
    rec = build_evidence_record(report(), base_manifest(), manifest(), None)
    jsonschema.validate(json.loads(rec.model_dump_json()), schema)
    assert EvidenceRecord.model_validate_json(rec.model_dump_json()) == rec


def test_wording_never_claims_compliance() -> None:
    text = (
        build_evidence_record(report(), base_manifest(), manifest(), None).model_dump_json().lower()
    )
    assert "compliant" not in text
    assert "konform" not in text
    assert "supports documentation for accuracy, robustness and record-keeping" in text


def test_reviewer_is_optional() -> None:
    rec = build_evidence_record(report(), base_manifest(), manifest(), None)
    assert rec.reviewer is None


def test_no_baseline_record_has_empty_baseline_fields() -> None:
    rec = build_evidence_record(no_baseline_report(), None, manifest(), None)
    assert rec.no_baseline
    assert rec.gate_status is GateStatus.INSUFFICIENT_DATA
    assert rec.baseline is None
    assert rec.baseline_run_id is None
    assert rec.results == ()
    EvidenceRecord.model_validate_json(rec.model_dump_json())


def test_base_none_with_a_baseline_id_keeps_the_id() -> None:
    rec = build_evidence_record(gate_report(), None, manifest(), None)
    assert rec.baseline is None
    assert rec.baseline_run_id == "20261101T220000-ba5e00"


def test_artefact_hashes_default_to_empty_and_extra_fields_are_refused() -> None:
    rec = build_evidence_record(report(), base_manifest(), manifest(), None)
    assert rec.gate_json_sha256 is None
    assert rec.candidate.run_json_sha256 is None
    assert rec.thresholds is None
    with pytest.raises(ValidationError):
        EvidenceRecord.model_validate({**rec.model_dump(), "surprise": 1})


def test_sha256_helper_matches_hashlib(tmp_path: Path) -> None:
    path = tmp_path / "run.json"
    path.write_bytes(b'{"a": 1}\n')
    assert sha256_file(path) == hashlib.sha256(b'{"a": 1}\n').hexdigest()
    assert sha256_file(tmp_path / "missing.json") is None
