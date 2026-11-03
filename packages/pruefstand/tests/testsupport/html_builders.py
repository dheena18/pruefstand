"""Builders for the HTML report tests (T6.4): real run results around the T1.9 gate reports."""

from typing import Any

from testsupport.report_builders import base_manifest, manifest
from testsupport.run_builders import make_case

from pruefstand.core.ids import CaseId, ChunkId, DocId, TenantId
from pruefstand.core.models.metric import MetricStatus, MetricValue
from pruefstand.core.models.run import RunManifest, RunResults, ScoredCase
from pruefstand.core.models.target import (
    CaseRecord,
    RetrievedChunk,
    TargetRequest,
    TargetResponse,
)

CHUNK_TEXT = "Kündigungsschutzgesetz § 23: Betriebe mit bis zu zehn Arbeitnehmern."
QUESTION = "Gilt das Kündigungsschutzgesetz für Kleinbetriebe?"


def chunks(
    case_id: str, text: str = CHUNK_TEXT, tenant: str = "public"
) -> tuple[RetrievedChunk, ...]:
    """Two chunks: rank 1 used in the prompt, rank 2 retrieved but not used."""
    return tuple(
        RetrievedChunk(
            chunk_id=ChunkId(f"{case_id}-c{rank}"),
            doc_id=DocId("gii-bgb-622"),
            tenant_id=TenantId(tenant),
            text=text,
            score=1.0 / rank,
            rank=rank,
            used_in_prompt=rank == 1,
        )
        for rank in (1, 2)
    )


def run_of(
    mf: RunManifest,
    indexes: tuple[int, ...] = (42, 107),
    *,
    answer: str = "Nein, nicht in Kleinbetrieben.",
    question: str = QUESTION,
    chunk_text: str = CHUNK_TEXT,
    truncated: tuple[int, ...] = (),
    **case: Any,
) -> RunResults:
    """A run with one case per index (``law-0042`` ...), each with an answer and two chunks."""
    records, scored = [], []
    for i in indexes:
        c = make_case(i, question=question, **case)
        records.append(
            CaseRecord(
                case_id=CaseId(c.id),
                request=TargetRequest(tenant_id=c.tenant, question=c.question, request_id=c.id),
                response=TargetResponse(
                    answer=answer,
                    citations=("§ 23 KSchG",),
                    chunks=chunks(c.id, chunk_text),
                    refused=False,
                ),
                error=None,
                latency_ms=10.0,
                cached=False,
                attempt=1,
            )
        )
        details: dict[str, str | float | int | bool] = {"truncated": True} if i in truncated else {}
        values = (
            MetricValue(
                metric="context_recall", metric_version="1", value=1.0, status=MetricStatus.OK
            ),
            MetricValue(
                metric="faithfulness",
                metric_version="1",
                value=0.5,
                status=MetricStatus.OK,
                details=details,
            ),
        )
        scored.append(ScoredCase(case=c, values=values))
    return RunResults(manifest=mf, records=tuple(records), values=tuple(scored))


def tier2_pair(**cand_changes: Any) -> tuple[RunResults, RunResults]:
    """Baseline and candidate runs of the tier-2 fixture (manifests of ``report_builders``)."""
    return run_of(base_manifest()), run_of(manifest(**cand_changes))
