"""Row and item formatters of the PR comment (ui-spec §10.2, §12). Pure; no layout decisions."""

from pruefstand.core.enums import GateStatus
from pruefstand.core.models.gate import HardFailFinding, SliceDecision
from pruefstand.report.format import (
    DASH,
    fmt_delta,
    fmt_mde,
    fmt_num,
    fmt_signed,
    md_code,
    md_escape,
)
from pruefstand.report.labels import METRIC_LABELS, REASON_LABELS
from pruefstand.report.tables import NO_REASON

OVERALL = "overall"
STATUS_WORDS = {
    GateStatus.PASS: "PASS",
    GateStatus.WARN: "WARN",
    GateStatus.FAIL: "FAIL",
    GateStatus.INSUFFICIENT_DATA: "INSUFFICIENT",
    GateStatus.UNSUPPORTED_CONFIG: "UNSUPPORTED",
}
EVIDENCE_LIMIT = 120


def row(*cells: str) -> str:
    """Join table cells into one Markdown table row."""
    return "| " + " | ".join(cells) + " |"


def label_md(metric: str) -> str:
    """Return the en label of ``metric``; an unknown name is escaped and shown as-is."""
    return METRIC_LABELS.get(metric) or md_escape(metric)


def reason_md(code: str) -> str:
    """Return the label of an informational reason; an unknown code is escaped and shown raw."""
    return REASON_LABELS.get(code) or (DASH if code == NO_REASON else md_escape(code))


def slice_cell(d: SliceDecision) -> str:
    """Return ``dimension=value``, escaped."""
    return f"{md_escape(d.dimension)}={md_escape(d.value)}"


def metric_with_slice(d: SliceDecision) -> str:
    """Return the metric label, plus ``· dimension=value`` unless the row is ``overall``."""
    base = label_md(d.metric)
    return base if d.dimension == OVERALL else f"{base} · {slice_cell(d)}"


def delta(d: SliceDecision) -> str:
    """Return ``Δ (95% CI)`` from the bootstrap result, or an en dash."""
    r = d.result
    return DASH if r is None else fmt_delta(r.mean_diff, r.ci_low, r.ci_high)


def mean_diff(d: SliceDecision) -> str:
    """Return the signed ``mean_diff`` from the result (never computed here), or an en dash."""
    return DASH if d.result is None else fmt_signed(d.result.mean_diff)


def overall_row(d: SliceDecision) -> str:
    """Return the 7-column row: Metric | Base | PR | Δ (95% CI) | δ | MDE | Status."""
    return row(
        label_md(d.metric), fmt_num(d.baseline_mean), fmt_num(d.candidate_mean), delta(d),
        fmt_mde(d.max_drop), fmt_mde(d.mde), STATUS_WORDS[d.status],
    )  # fmt: skip


def slice_row(d: SliceDecision) -> str:
    """Return the 8-column row of the "Gated slices not passing" table."""
    return row(slice_cell(d), overall_row(d)[2:-2])


def check_row(d: SliceDecision) -> str:
    """Return a tier-1 check row: Check | Value | Max | Status."""
    return row(
        metric_with_slice(d),
        fmt_num(d.candidate_mean),
        fmt_mde(d.max_value),
        STATUS_WORDS[d.status],
    )


def reported_row(d: SliceDecision) -> str:
    """Return a tier-1 reported row; no CI and no status word (ui-spec §11.1)."""
    reason = d.informational_reason or NO_REASON
    return row(
        metric_with_slice(d), fmt_num(d.baseline_mean), fmt_num(d.candidate_mean), mean_diff(d),
        fmt_mde(d.mde), fmt_mde(d.max_value), reason_md(reason),
    )  # fmt: skip


def info_item(d: SliceDecision, *, reason: bool = True) -> str:
    """Return ``Metric 0.80 → 0.78 (−0.02) — reason`` for the informational and judged lines."""
    text = f"{metric_with_slice(d)} {fmt_num(d.baseline_mean)} → {fmt_num(d.candidate_mean)}"
    if d.result is not None:
        text += f" ({fmt_signed(d.result.mean_diff)})"
    if reason:
        text += f" — {reason_md(d.informational_reason or NO_REASON)}"
    return text


def absolute_item(d: SliceDecision) -> str:
    """Return ``Injection success 0.03 (max 0.02) WARN`` for the absolute-checks line."""
    return (
        f"{metric_with_slice(d)} {fmt_num(d.candidate_mean)} (max {fmt_mde(d.max_value)}) "
        f"{STATUS_WORDS[d.status]}"
    )


def notable_item(d: SliceDecision) -> str:
    """Return ``dimension=value −0.18`` for the notable-slice line."""
    suffix = "" if d.result is None else f" {fmt_signed(d.result.mean_diff)}"
    return f"{slice_cell(d)}{suffix}"


def insufficient_item(d: SliceDecision) -> str:
    """Return ``Metric · dimension=value (n clusters)`` for the insufficient-data line."""
    where = OVERALL if d.dimension == OVERALL else slice_cell(d)
    count = "" if d.n_clusters is None else f" ({d.n_clusters} clusters)"
    return f"{label_md(d.metric)} · {where}{count}"


def hard_fail_row(finding: HardFailFinding) -> str:
    """Return a hard-fail row: Rule | Case | Metric | Evidence (redacted)."""
    metric = md_escape(finding.metric)
    rule = metric if finding.rule == "hard_fail" else f"{metric} (unverifiable)"
    evidence = md_code(finding.evidence, limit=EVIDENCE_LIMIT)
    return row(rule, md_escape(finding.case_id), metric, evidence)
