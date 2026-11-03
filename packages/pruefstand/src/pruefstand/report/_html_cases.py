"""Failing-case cards and the run-metadata table of the HTML report (ui-spec §13).

Everything shown here is cleaned (canaries masked, control characters dropped, length capped);
chunk text is shown only when the run still holds it (a private render), a sanitised run has empty
chunk texts and the card says so.
"""

from collections.abc import Mapping
from typing import Any

from pruefstand.core.config.gate import JUDGED_METRICS
from pruefstand.core.ids import CaseId
from pruefstand.core.models.run import RunManifest, RunResults, ScoredCase
from pruefstand.core.models.target import CaseRecord, RetrievedChunk
from pruefstand.report._html_tables import Table, cell, row, table
from pruefstand.report._html_text import clean, clean_block
from pruefstand.report.format import DASH, fmt_duration, fmt_usd

MAX_CARDS = 20
MAX_CHUNKS = 10
MAX_CITATIONS = 20
SHARED_TENANT = "public"
MAX_CHUNK_TEXT = 3000


def _chunk(chunk: RetrievedChunk, case_tenant: str) -> dict[str, Any]:
    tenant = chunk.tenant_id
    foreign = tenant is not None and tenant not in {case_tenant, SHARED_TENANT}
    return {
        "rank": chunk.rank,
        "chunk_id": clean(chunk.chunk_id, 80),
        "doc_id": clean(chunk.doc_id, 80),
        "tenant": clean(tenant, 60) or DASH,
        "leak": foreign,
        "score": f"{chunk.score:.2f}",
        "not_used": chunk.used_in_prompt is False,
        "text": clean_block(chunk.text, MAX_CHUNK_TEXT),
    }


def _answer(record: CaseRecord | None, tenant: str) -> dict[str, Any] | None:
    if record is None:
        return None
    resp = record.response
    chunks = (resp.chunks or ())[:MAX_CHUNKS] if resp else ()
    return {
        "text": clean_block(resp.answer) if resp else "",
        "refused": bool(resp and resp.refused),
        "error": clean(record.error) if record.error else None,
        "citations": [clean(c, 120) for c in (resp.citations if resp else ())[:MAX_CITATIONS]],
        "chunks": [_chunk(c, tenant) for c in chunks],
    }


def card(
    case_id: CaseId,
    scored: ScoredCase | None,
    cand: CaseRecord | None,
    base: CaseRecord | None,
    *,
    has_base: bool,
) -> dict[str, Any]:
    """Return the view of one failing case.

    ``scored`` / ``cand`` may be missing (a case that sanitising dropped): the card then shows the
    id only. ``has_base`` is false when no baseline run is available (no baseline answer).
    """
    case = scored.case if scored else None
    question = case.question if case else (cand.request.question if cand else "")
    tenant = case.tenant if case else ""
    return {
        "id": clean(case_id, 80),
        "known": scored is not None or cand is not None,
        "lang": case.lang.value if case else "de",
        "question": clean_block(question),
        "category": clean(case.category.value, 40) if case else DASH,
        "tenant": clean(tenant, 60) or DASH,
        "expect_refusal": bool(case and case.expect_refusal),
        "answer": _answer(cand, tenant),
        "base_answer": _answer(base, tenant) if has_base else None,
    }


def cards(
    ids: tuple[CaseId, ...], cand: RunResults, base: RunResults | None
) -> list[dict[str, Any]]:
    """Return up to ``MAX_CARDS`` cards for ``ids`` (``GateReport.top_failing_cases``)."""
    scored = {s.case.id: s for s in cand.values}
    records = {r.case_id: r for r in cand.records}
    base_records = {r.case_id: r for r in base.records} if base is not None else {}
    return [
        card(i, scored.get(i), records.get(i), base_records.get(i), has_base=base is not None)
        for i in ids[:MAX_CARDS]
    ]


def truncated_cases(cand: RunResults) -> list[str]:
    """Return the ids of the cases whose judge input was truncated (X3.9), sorted."""
    return sorted(
        {
            clean(s.case.id, 80)
            for s in cand.values
            for v in s.values
            if v.metric in JUDGED_METRICS and v.details.get("truncated") is True
        }
    )


def _kv(mapping: Mapping[str, str] | Mapping[str, int]) -> str:
    if not mapping:
        return DASH
    return ", ".join(f"{clean(k, 60)}={clean(str(v), 80)}" for k, v in sorted(mapping.items()))


def _meta_rows(m: RunManifest) -> list[tuple[str, str]]:
    models = m.target.models if m.target else {}
    return [
        ("Run id", clean(m.run_id, 80)),
        ("Created (UTC)", m.created_at.strftime("%Y-%m-%d %H:%M UTC")),
        ("Git SHA", clean(m.git_sha, 64) or DASH),
        ("Git ref", clean(m.git_ref, 80) or DASH),
        ("PR", DASH if m.pr_number is None else f"#{m.pr_number}"),
        ("Prüfstand version", clean(m.pruefstand_version, 40)),
        ("Eval fingerprint", clean(m.eval_fingerprint, 64)),
        ("Target fingerprint", clean(m.target_fingerprint, 64)),
        ("Config hash", clean(m.config_hash, 64)),
        ("Dataset", f"{clean(m.dataset_name, 60)} {clean(m.dataset_version, 40)}"),
        (
            "Splits",
            ", ".join(s.value for s in m.splits)
            + (f" block {m.block}" if m.block is not None else ""),
        ),
        ("Stack · workload", f"{m.stack} · {m.workload}"),
        ("Stratum", m.stratum),
        ("Cases · seed", f"{m.n_cases} · {m.seed}"),
        ("Duration · cost", f"{fmt_duration(m.duration_s)} · {fmt_usd(m.cost.usd)}"),
        (
            "Stop reason",
            clean(m.stop_reason, 40)
            + ("" if m.infra_error is None else f" ({clean(m.infra_error, 120)})"),
        ),
        ("Target models", _kv(models)),
        ("Judge mode", m.judge_mode),
        ("Judge models", _kv(m.judge_models)),
        ("Judge prompt versions", _kv(m.judge_prompt_versions)),
        ("Metric versions", _kv(m.metric_versions)),
        ("Counts", _kv(m.counts)),
    ]


def metadata_table(base: RunManifest | None, cand: RunManifest) -> Table:
    """Return the Run-metadata table; the baseline column is ``–`` without a baseline manifest."""
    mine = _meta_rows(cand)
    theirs = dict(_meta_rows(base)) if base is not None else {}
    rows = [
        row(cell(name), cell(theirs.get(name, DASH), mono=True), cell(value, mono=True))
        for name, value in mine
    ]
    return table(
        "Run metadata", (("Field", False), ("Baseline", False), ("Candidate", False)), rows
    )
