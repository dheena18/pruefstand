"""View model of the HTML report (ui-spec §13): header, banners and the tables of every section.

Table membership is ``report.tables.assign_block`` through the PR comment's ``Builder`` (one rule,
ui-spec §11.1); this module only lays the blocks out. Pure: no I/O, no clock, no computation of
statistics.
"""

from typing import Any

from pruefstand.core.config.gate import JUDGED_METRICS
from pruefstand.core.enums import GateStatus
from pruefstand.core.models.gate import CAUSE_MESSAGES, GateReport, SliceDecision
from pruefstand.core.models.run import RunManifest, RunResults
from pruefstand.report import _html_cases as hc
from pruefstand.report import _html_tables as ht
from pruefstand.report import labels as lb
from pruefstand.report._context import FULL, Builder
from pruefstand.report._html_text import clean
from pruefstand.report.format import DASH, fmt_duration, fmt_gpu, fmt_tokens, fmt_usd
from pruefstand.report.tables import Block
from pruefstand.report.truncation import judge_truncated_case_ids

GATED_COLS = (
    ("Metric", False), ("Base", True), ("PR", True), ("Δ (95% CI)", True), ("δ", True),
    ("MDE", True), ("Status", False),
)  # fmt: skip
CHECK_COLS = (("Check", False), ("Value", True), ("Max", True), ("Status", False))
REPORTED_COLS = (
    ("Metric", False), ("Base", True), ("PR", True), ("Δ", True), ("MDE", True), ("Max", True),
    ("Reported because", False),
)  # fmt: skip
INFO_COLS = (
    ("Metric", False), ("Base", True), ("PR", True), ("Δ", True), ("Reason", False),
)  # fmt: skip
JUDGED_COLS = (
    ("Metric", False), ("Base", True), ("PR", True), ("Δ", True), ("Judged cases", True),
)  # fmt: skip
NOTABLE_COLS = (
    ("Slice", False), ("Metric", False), ("Base", True), ("PR", True), ("Δ", True),
    ("Notable", False),
)  # fmt: skip
NO_BASELINE_TEXT = (
    "No baseline for this evaluation fingerprint — nothing was compared. Run baseline-promote."
)
NO_CERT = "Supports documentation, not a compliance certificate."
HEADLINE = {
    GateStatus.PASS: ("s-pass", "✅", "PASS"),
    GateStatus.WARN: ("s-warn", "⚠️", "WARN"),
    GateStatus.UNSUPPORTED_CONFIG: ("s-warn", "⚠️", "WARN"),
    GateStatus.FAIL: ("s-fail", "❌", "FAIL"),
    GateStatus.INSUFFICIENT_DATA: ("s-insufficient", "◌", "INSUFFICIENT DATA"),
}


def _ref(m: RunManifest) -> str:
    label = f"pr-{m.pr_number}" if m.pr_number is not None else clean(m.git_ref, 80)
    sha = clean(m.git_sha, 64)
    short = f"@{sha[:7]}" if sha else ""
    return f"{label}{short}" or DASH


def _baseline_ref(report: GateReport, base: RunManifest | None) -> str:
    if base is not None:
        return _ref(base)
    return clean(report.baseline_run_id, 64) or DASH


def _banner(kind: str, icon: str, text: str, role: str = "status") -> dict[str, str]:
    return {"cls": kind, "icon": icon, "text": text, "role": role}


def banners(b: Builder) -> list[dict[str, str]]:
    """Return the banners in ui-spec §13 order (each only when its state holds)."""
    c, report, out = b.cand, b.report, []
    if not c.complete:
        out.append(
            _banner(
                "warn",
                "⚠️",
                f"Incomplete run — not gated (stop reason: {clean(c.stop_reason, 40)}).",
            )
        )
    if report.no_baseline:
        out.append(
            _banner(
                "fail",
                "❌",
                NO_BASELINE_TEXT,
                "alert",
            )
        )
    if report.status is GateStatus.UNSUPPORTED_CONFIG:
        out.append(_banner("warn", "⚠️", lb.NOTICE_UNSUPPORTED))
    if b.tier1:
        out.append(_banner("info", lb.ICON_INFO, lb.NOTICE_TIER1.replace("`", "")))
    if c.judge_mode == "skipped":
        out.append(_banner("info", lb.ICON_INFO, lb.NOTICE_JUDGE_SKIPPED))
    for flag, text in (
        (c.judge_fallback, lb.NOTICE_JUDGE_FALLBACK),
        (c.judge_degraded, lb.NOTICE_JUDGE_DEGRADED),
        (c.judge_drift, lb.NOTICE_JUDGE_DRIFT),
    ):
        if flag:
            out.append(_banner("warn", "⚠️", text))
    out.append(_banner("neutral", lb.ICON_INFO, NO_CERT))
    return out


def header(b: Builder, base: RunManifest | None) -> dict[str, Any]:
    """Return the header block: status badge, tier, blocking count, cause, refs and run facts."""
    c, report = b.cand, b.report
    if report.no_baseline:
        badge = ("s-insufficient", "⚪", "NO BASELINE")
    else:
        badge = HEADLINE[report.status]
    cause = None
    if report.likely_cause is not None:
        cause = CAUSE_MESSAGES[report.likely_cause].replace(": <codes>", "")
    splits = ", ".join(s.value for s in c.splits)
    if c.block is not None:
        splits += f" block {c.block}"
    facts = [splits, f"{c.n_cases} cases", fmt_duration(c.duration_s), fmt_usd(c.cost.usd),
             f"{fmt_tokens(c.cost)} tokens"]  # fmt: skip
    if not b.tier1:
        facts.append(fmt_gpu(c.cost.gpu_seconds))
    facts.append(c.created_at.strftime("created %Y-%m-%d %H:%M UTC"))
    n = b.blocking()
    noun = "issue" if n == 1 else "issues"
    return {
        "cls": badge[0], "icon": badge[1], "word": badge[2],
        "tier": "Tier 1" if b.tier1 else "Tier 2",
        "blocking": None if report.no_baseline else f"{n} blocking {noun}",
        "cause": cause, "likely_code": report.likely_cause,
        "baseline": _baseline_ref(report, base), "candidate": _ref(c), "facts": facts,
    }  # fmt: skip


def _severity(d: SliceDecision) -> tuple[int, int, float, str, str, str]:
    thin = d.status is GateStatus.INSUFFICIENT_DATA
    rank = {GateStatus.FAIL: 0, GateStatus.WARN: 1, GateStatus.UNSUPPORTED_CONFIG: 1}
    diff = d.result.mean_diff if d.result else float("inf")
    return (int(thin), rank.get(d.status, 2), diff, d.dimension, d.value, d.metric)


def hard_fails(report: GateReport) -> ht.Table | None:
    """Return the hard-fail table (redacted evidence), or ``None``."""
    if not report.hard_fails:
        return None
    rows = [ht.hard_fail_row(f) for f in report.hard_fails]
    cols = (("Rule", False), ("Case", False), ("Metric", False), ("Evidence (redacted)", False))
    return ht.table(f"Hard fails ({len(rows)})", cols, rows)


def _in_metrics(b: Builder, d: SliceDecision) -> bool:
    return (
        not b.tier1 and d.dimension == ht.OVERALL and d.status is not GateStatus.INSUFFICIENT_DATA
    )


def metrics(b: Builder) -> list[ht.Table]:
    """Return the Metrics tables (tier 2: block G overall; tier 1: hard-fail row + C, then R)."""
    if b.report.no_baseline:
        return []
    if not b.tier1:
        rows = [ht.gated_row(d, with_slice=False) for d in b.blocks[Block.G] if _in_metrics(b, d)]
        title = "Gated metrics (overall)"
        return [ht.table(title, GATED_COLS, rows)] if rows else []
    n = len(b.report.hard_fails)
    head = ht.row(
        ht.cell(lb.TIER1_HARD_FAIL_ROW), ht.cell(str(n), num=True), ht.cell("0", num=True),
        ht.status_cell(GateStatus.FAIL if n else GateStatus.PASS),
    )  # fmt: skip
    out = [ht.table("Checks (decide)", CHECK_COLS, [head, *map(ht.check_row, b.blocks[Block.C])])]
    reported = b.blocks[Block.R]
    if reported:
        caption = f"Reported — does not decide at n = {b.cand.n_cases}"
        out.append(ht.table(caption, REPORTED_COLS, [ht.reported_row(d) for d in reported]))
    return out


def slices(b: Builder) -> list[ht.Table]:
    """Return the Slices tables: block G (insufficient greyed), block N, not applicable."""
    if b.report.no_baseline:
        return []
    out: list[ht.Table] = []
    g = sorted((d for d in b.blocks[Block.G] if not _in_metrics(b, d)), key=_severity)
    if g:
        rows = [ht.gated_row(d, with_slice=True) for d in g]
        cols = (("Slice", False), *GATED_COLS)
        out.append(ht.table("Gated slices", cols, rows, sortable=True))
    notable = b.blocks[Block.N]
    if notable:
        rows = [ht.notable_row(d) for d in notable]
        caption = "Notable slices — informational, does not block"
        out.append(ht.table(caption, NOTABLE_COLS, rows, sortable=True))
    counts = b.report.not_applicable_counts
    if counts:
        rows = [
            ht.row(ht.cell(ht.label(k)), ht.cell(str(v), num=True))
            for k, v in sorted(counts.items())
        ]
        out.append(ht.table("Not applicable", (("Metric", False), ("Cases", True)), rows))
    out.extend(_not_paired(b))
    return out


def _not_paired(b: Builder) -> list[ht.Table]:
    """Return the table of cases dropped from a paired metric's comparison, or nothing."""
    names = sorted(set(b.report.n_unmatched) | set(b.report.n_excluded))
    if not names:
        return []
    rows = [
        ht.row(
            ht.cell(ht.label(k)),
            ht.cell(str(b.report.n_unmatched.get(k, 0)), num=True),
            ht.cell(str(b.report.n_excluded.get(k, 0)), num=True),
        )
        for k in names
    ]
    cols = (("Metric", False), ("In one run only", True), ("Excluded", True))
    return [ht.table("Not paired (dropped from the comparison)", cols, rows)]


def absolute(b: Builder) -> ht.Table | None:
    """Return the tier-2 Absolute checks table (block A), or ``None``."""
    rows = b.blocks[Block.A]
    if b.tier1 or b.report.no_baseline or not rows:
        return None
    return ht.table("Absolute checks", CHECK_COLS, [ht.check_row(d) for d in rows])


def informational(b: Builder, cand: RunResults) -> dict[str, Any]:
    """Return the Informational section: blocks I and J (or the skipped text), truncation."""
    c = b.cand
    rows = b.blocks[Block.I]
    judged = list(b.blocks[Block.J]) if b.tier1 else [d for d in rows if d.metric in JUDGED_METRICS]
    plain = [d for d in rows if b.tier1 or d.metric not in JUDGED_METRICS]
    skipped = c.judge_mode == "skipped"
    if skipped:
        plain, judged = [*plain, *judged], []
    plain.sort(key=lambda d: (d.informational_reason or "~", d.metric, d.dimension, d.value))
    out: dict[str, Any] = {"tables": [], "judged": None, "skipped": skipped, "truncated": None}
    if plain and not b.report.no_baseline:
        out["tables"].append(
            ht.table("Informational (does not block)", INFO_COLS, [ht.info_row(d) for d in plain])
        )
    if not b.report.no_baseline and not skipped and (judged or c.judged_subset):
        source = lb.JUDGE_SOURCE[c.judge_mode]
        heading = (
            f"Judged metrics — informational, does not block ({source}, {c.judged_cases} cases)"
        )
        if c.judged_subset:
            heading += f" · {lb.JUDGED_SUBSET}"
        shown = [ht.judged_row(d, c.judged_cases) for d in judged]
        out["judged"] = {
            "heading": heading,
            "table": ht.table(heading, JUDGED_COLS, shown) if shown else None,
        }
    cut = c.counts.get("judge_truncated", 0)
    if cut > 0:
        noun = "case" if cut == 1 else "cases"
        out["truncated"] = {
            "text": f"Judge input truncated on {cut} {noun}; those judgments may be incomplete.",
            "ids": [clean(i, 80) for i in judge_truncated_case_ids(cand)],
        }
    return out


def build_view(report: GateReport, base: RunResults | None, cand: RunResults) -> dict[str, Any]:
    """Return everything the template lays out (all strings clean, all numbers formatted)."""
    base_m = None if base is None else base.manifest
    b = Builder(report, base_m, cand.manifest, None, FULL)
    return {
        "header": header(b, base_m),
        "banners": banners(b),
        "no_baseline": report.no_baseline,
        "hard_fails": hard_fails(report),
        "metrics": metrics(b),
        "slices": slices(b),
        "absolute": absolute(b),
        "info": informational(b, cand),
        "cards": hc.cards(report.top_failing_cases, cand, base),
        "meta": hc.metadata_table(base_m, cand.manifest),
        "run_id": clean(cand.manifest.run_id, 80),
        "version": clean(cand.manifest.pruefstand_version, 40),
        "tier1": b.tier1,
    }
