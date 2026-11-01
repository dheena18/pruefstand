"""Builders for runner and store tests: real models, no fakes of the target or of models."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pruefstand.core.ids import CaseId, TenantId
from pruefstand.core.models.metric import MetricStatus, MetricValue
from pruefstand.core.models.run import CostSummary, RunManifest, RunResults, ScoredCase
from pruefstand.core.models.target import (
    CaseRecord,
    RetrievedChunk,
    TargetRequest,
    TargetResponse,
)
from pruefstand.core.models.testcase import TestCase

_CASE: dict[str, Any] = {
    "tenant": "public",
    "lang": "de",
    "question": "Welche Kündigungsfrist gilt für den Arbeitgeber nach zwei Jahren?",
    "reference_answer": "Einen Monat zum Ende eines Kalendermonats (§ 622 Abs. 2 Nr. 1 BGB).",
    "gold_doc_ids": ["gii-bgb-622"],
    "gold_citations": ["§ 622 Abs. 2 Nr. 1 BGB"],
    "category": "factual",
    "difficulty": "easy",
    "split": "core",
    "source": "generated+reviewed",
    "license_config": "laws_eurlex",
    "corpus_version": "2026-11-02.ab12cd34",
}


def make_case(index: int, **changes: Any) -> TestCase:
    """Build case ``law-<index>``; keyword arguments override the factual default."""
    case_id = f"law-{index:04d}"
    return TestCase.model_validate({**_CASE, "id": case_id, "base_id": case_id, **changes})


def make_cases(count: int, **changes: Any) -> list[TestCase]:
    """Build ``count`` factual cases ``law-0000`` ... ."""
    return [make_case(i, **changes) for i in range(count)]


def make_manifest(**changes: Any) -> RunManifest:
    """Build a complete manifest; keyword arguments override fields."""
    data: dict[str, Any] = {
        "schema_version": "1",
        "run_id": "20261102T220000-ab12cd",
        "created_at": datetime(2026, 11, 2, 22, 0, tzinfo=UTC),
        "pruefstand_version": "0.0.1",
        "git_sha": None,
        "git_ref": None,
        "pr_number": None,
        "target": None,
        "target_fingerprint": "t" * 16,
        "eval_fingerprint": "e" * 16,
        "dataset_name": "pruefstand-de",
        "dataset_version": "v1",
        "splits": ["core"],
        "n_cases": 2,
        "config_hash": "c" * 16,
        "judge_models": {},
        "judge_prompt_versions": {},
        "metric_versions": {"context_recall": "1"},
        "seed": 7,
        "cost": CostSummary(
            usd=0, prompt_tokens=0, completion_tokens=0, gpu_seconds=0, llm_calls=0
        ),
        "duration_s": 1.5,
        "counts": {"ok": 2},
        "complete": True,
        "stop_reason": "completed",
        "stack": "live",
        "workload": "pr",
        "judge_mode": "skipped",
    }
    return RunManifest.model_validate({**data, **changes})


def make_results(count: int = 2) -> RunResults:
    """Build a small, fully populated ``RunResults`` with German text and metric details."""
    cases = make_cases(count, question="Gilt das Kündigungsschutzgesetz für Kleinbetriebe?")
    records: list[CaseRecord] = []
    scored: list[ScoredCase] = []
    for case in cases:
        chunk = RetrievedChunk.model_validate(
            {
                "chunk_id": f"{case.id}-c1",
                "doc_id": "gii-bgb-622",
                "tenant_id": "public",
                "text": "Kündigungsschutzgesetz § 23: Betriebe mit bis zu zehn Arbeitnehmern.",
                "score": 0.9,
                "rank": 1,
            }
        )
        records.append(
            CaseRecord(
                case_id=CaseId(case.id),
                request=TargetRequest(
                    tenant_id=TenantId("public"), question=case.question, request_id="r" + case.id
                ),
                response=TargetResponse(answer="Nein, nicht in Kleinbetrieben.", chunks=(chunk,)),
                error=None,
                latency_ms=12.5,
                cached=False,
                attempt=1,
            )
        )
        values = (
            MetricValue(
                metric="context_recall",
                metric_version="1",
                value=1.0,
                status=MetricStatus.OK,
                details={"matched": 1, "note": "Kündigungsschutzgesetz"},
            ),
            MetricValue(
                metric="language_match",
                metric_version="1",
                value=None,
                status=MetricStatus.NOT_APPLICABLE,
                details={"reason": "category"},
            ),
        )
        scored.append(ScoredCase(case=case, values=values))
    return RunResults(
        manifest=make_manifest(n_cases=count), records=tuple(records), values=tuple(scored)
    )


def refresh_hashes(run_dir: Path) -> None:
    """Re-hash the data files of a run directory into ``run.json`` (after a test edited them)."""
    manifest = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    manifest["artifact_sha256"] = {
        name: hashlib.sha256((run_dir / name).read_bytes()).hexdigest()
        for name in ("responses.jsonl", "results.parquet", "scored.jsonl")
    }
    (run_dir / "run.json").write_text(json.dumps(manifest), encoding="utf-8")


def unhashed(results: RunResults) -> RunResults:
    """Drop ``artifact_sha256`` (set by ``write_run``) so a read run equals the original."""
    manifest = results.manifest.model_copy(update={"artifact_sha256": {}})
    return results.model_copy(update={"manifest": manifest})
