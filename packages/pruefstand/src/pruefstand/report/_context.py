"""View model of the PR comment: turns a ``GateReport`` into the strings the template lays out.

Every case- or target-derived string passes ``md_escape`` / ``md_code`` here; the template never
sees a raw value. Lists are capped by ``Limits`` so the output stays bounded; ``truncated`` is set
as soon as anything was cut. No number is computed: all of them are copied from the models.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from pruefstand.core.config.gate import JUDGED_METRICS
from pruefstand.core.enums import GateStatus
from pruefstand.core.models.gate import GateReport, SliceDecision
from pruefstand.core.models.run import RunManifest
from pruefstand.report import _rows as r
from pruefstand.report import labels as lb
from pruefstand.report.format import (
    DASH,
    fmt_duration,
    fmt_gpu,
    fmt_tokens,
    fmt_usd,
    md_code,
    md_escape,
    ref_label,
    safe_url,
)
from pruefstand.report.labels import ICON_INFO
from pruefstand.report.tables import Block, Source, assign_block

MARKER = "<!-- pruefstand:pr-comment -->"
DETAILS_ROWS = 5
TITLES = {
    GateStatus.PASS: "✅ PASS",
    GateStatus.WARN: "⚠️ WARN",
    GateStatus.UNSUPPORTED_CONFIG: "⚠️ WARN",
    GateStatus.FAIL: "❌ FAIL",
    GateStatus.INSUFFICIENT_DATA: "◌ INSUFFICIENT DATA",
}
SLICE_HEAD = (
    "| Slice | Metric | Base | PR | Δ (95% CI) | δ | MDE | Status |",
    "|---|---|---|---|---|---|---|---|",
)
OVERALL_HEAD = (
    "| Metric | Base | PR | Δ (95% CI) | δ | MDE | Status |",
    "|---|---|---|---|---|---|---|",
)
HARD_HEAD = ("| Rule | Case | Metric | Evidence (redacted) |", "|---|---|---|---|")
CHECK_HEAD = ("| Check | Value | Max | Status |", "|---|---|---|---|")
REPORTED_HEAD = (
    "| Metric | Base | PR | Δ | MDE | Max | Reported because |",
    "|---|---|---|---|---|---|---|",
)


@dataclass(frozen=True)
class Limits:
    """Caps that keep the comment bounded; tighter steps are tried when it exceeds 60 000 chars."""

    slices: int
    items: int
    fails: int
    ids: int


FULL = Limits(slices=1000, items=25, fails=50, ids=50)
TIGHT = Limits(slices=20, items=10, fails=10, ids=20)
MINIMAL = Limits(slices=0, items=5, fails=5, ids=5)


def _table(
    head: tuple[str, str], rows: Sequence[str], summary: str, *, force: bool = False
) -> dict[str, Any]:
    return {
        "summary": summary,
        "lines": [*head, *rows],
        "details": force or len(rows) > DETAILS_ROWS,
    }


def _severity(d: SliceDecision) -> tuple[int, float, str, str, str]:
    rank = {GateStatus.FAIL: 0, GateStatus.WARN: 1, GateStatus.UNSUPPORTED_CONFIG: 1}
    diff = d.result.mean_diff if d.result else float("inf")
    return (rank.get(d.status, 2), diff, d.dimension, d.value, d.metric)


@dataclass
class Builder:
    report: GateReport
    base: RunManifest | None
    cand: RunManifest
    url: str | None
    lim: Limits
    truncated: bool = False
    blocks: dict[Block, list[SliceDecision]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.tier1 = self.cand.stack == "live"
        self.blocks = {b: [] for b in Block}
        pairs: tuple[tuple[Source, Sequence[SliceDecision]], ...] = (
            ("decisions", self.report.decisions),
            ("absolute_checks", self.report.absolute_checks),
            ("notable_slices", self.report.notable_slices),
        )
        for source, rows in pairs:
            for d in rows:
                self.blocks[assign_block(d, source, self.cand.stack)].append(d)

    marker = MARKER

    def cap[T](self, items: Sequence[T], limit: int) -> Sequence[T]:
        if len(items) > limit:
            self.truncated = True
        return items[:limit]

    def checks_block(self) -> list[SliceDecision]:
        return self.blocks[Block.C if self.tier1 else Block.A]

    def blocking(self) -> int:
        gated = [*self.blocks[Block.G], *self.checks_block()]
        return len(self.report.hard_fails) + sum(d.status is GateStatus.FAIL for d in gated)

    def title(self) -> str:
        prefix = "## Prüfstand tier 1:" if self.tier1 else "## Prüfstand:"
        if self.report.no_baseline:
            return f"{prefix} ⚪ NO BASELINE (nothing compared)"
        n = self.blocking()
        noun = "blocking issue" if n == 1 else "blocking issues"
        return f"{prefix} {TITLES[self.report.status]} ({n} {noun})"

    def refs(self) -> str:
        if self.base is not None:
            baseline = ref_label(self.base)
        elif self.report.baseline_run_id is not None:
            baseline = md_code(self.report.baseline_run_id, limit=64)
        else:
            baseline = DASH
        splits = ", ".join(s.value for s in self.cand.splits)
        if self.cand.block is not None:
            splits += f" block {self.cand.block}"
        c = self.cand
        parts = [f"Baseline: {baseline}", f"Candidate: {ref_label(c)}", splits,
                 f"{c.n_cases} cases", fmt_duration(c.duration_s), fmt_usd(c.cost.usd),
                 f"{fmt_tokens(c.cost)} tokens"]  # fmt: skip
        if not self.tier1:
            parts.append(fmt_gpu(c.cost.gpu_seconds))
        return " · ".join(p for p in parts if p)

    def notices(self) -> list[str]:
        c, out = self.cand, []
        if self.tier1:
            out.append(f"> {ICON_INFO} {lb.NOTICE_TIER1}")
        if self.report.no_baseline:
            fp = md_escape(self.report.eval_fingerprint, limit=64)
            out.append(f"> ❌ No baseline for {fp}; run baseline-promote. Nothing was compared.")
        if self.report.status is GateStatus.UNSUPPORTED_CONFIG:
            out.append(f"> ⚠️ {lb.NOTICE_UNSUPPORTED}")
        if c.judge_mode == "skipped" and not self.tier1:
            out.append(f"> {ICON_INFO} {lb.NOTICE_JUDGE_SKIPPED}")
        if c.judge_fallback:
            out.append(f"> ⚠️ {lb.NOTICE_JUDGE_FALLBACK}")
        if c.judge_degraded:
            out.append(f"> ⚠️ {lb.NOTICE_JUDGE_DEGRADED}")
        if c.judge_drift:
            out.append(f"> ⚠️ {lb.NOTICE_JUDGE_DRIFT}")
        return out

    def hard_fails(self) -> dict[str, Any] | None:
        fails = self.report.hard_fails
        if not fails:
            return None
        rows = [r.hard_fail_row(f) for f in self.cap(fails, self.lim.fails)]
        return {"count": len(fails), "table": _table(HARD_HEAD, rows, f"Hard fails ({len(fails)})")}

    def checks(self) -> dict[str, Any] | None:
        if not self.tier1 or self.report.no_baseline:
            return None
        n = len(self.report.hard_fails)
        head_row = r.row(lb.TIER1_HARD_FAIL_ROW, str(n), "0", "FAIL" if n else "PASS")
        rows = [
            head_row,
            *(r.check_row(d) for d in self.cap(self.blocks[Block.C], self.lim.items * 4)),
        ]
        return _table(CHECK_HEAD, rows, "Checks")

    def gated_tables(self) -> tuple[dict[str, Any] | None, dict[str, Any] | None, list[str]]:
        if self.report.no_baseline:
            return None, None, []
        overall, slices, thin = [], [], []
        for d in self.blocks[Block.G]:
            if d.status is GateStatus.INSUFFICIENT_DATA:
                thin.append(r.insufficient_item(d))
            elif d.dimension == r.OVERALL:
                overall.append(d)
            elif d.status is not GateStatus.PASS:
                slices.append(d)
        top = None
        if overall:
            rows = [r.overall_row(d) for d in self.cap(overall, 200)]
            top = _table(OVERALL_HEAD, rows, f"Gated metrics (overall) ({len(overall)})")
        bottom = None
        if slices:
            worst = self.cap(sorted(slices, key=_severity), self.lim.slices)
            bottom = _table(SLICE_HEAD, [r.slice_row(d) for d in worst],
                            f"Gated slices not passing ({len(slices)})", force=True)  # fmt: skip
        return top, bottom, thin

    def reported(self) -> dict[str, Any] | None:
        rows = self.blocks[Block.R]
        if not self.tier1 or not rows or self.report.no_baseline:
            return None
        shown = [r.reported_row(d) for d in self.cap(rows, self.lim.slices + 20)]
        summary = f"Reported, does not decide at n = {self.cand.n_cases} ({len(rows)})"
        return _table(REPORTED_HEAD, shown, summary, force=True)

    def joined(self, label: str, items: Sequence[str], sep: str = ", ") -> str | None:
        if not items:
            return None
        shown = self.cap(items, self.lim.items)
        more = len(items) - len(shown)
        tail = f"{sep}… and {more} more" if more else ""
        return f"{label} {sep.join(shown)}{tail}"

    def top_failing(self) -> str | None:
        ids = self.report.top_failing_cases
        note = "" if safe_url(self.url) else "(full report in the private executor run)"
        if not ids:
            return note or None
        shown = ", ".join(md_escape(i, limit=80) for i in self.cap(ids, self.lim.ids))
        return f"Top failing cases: {shown} {note}".rstrip()

    def footer(self) -> str:
        url = safe_url(self.url)
        tail = (
            "statistical gate: tier 2"
            if self.tier1
            else "WARN does not block unless --fail-on-warn"
        )
        parts = [f"[Full report](<{url}>)"] if url else []
        parts += [f"pruefstand v{md_escape(self.cand.pruefstand_version, limit=40)}", tail]
        return "<sub>" + " · ".join(parts) + "</sub>"

    def judged_cases(self) -> list[SliceDecision]:
        return [d for d in self.blocks[Block.I] if d.metric in JUDGED_METRICS]
