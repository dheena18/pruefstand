"""The single-line sections of the PR comment (ui-spec §12): informational, judged, notable, ..."""

from pruefstand.core.config.gate import JUDGED_METRICS
from pruefstand.core.enums import GateStatus
from pruefstand.core.models.gate import CAUSE_MESSAGES
from pruefstand.report import _rows as r
from pruefstand.report import labels as lb
from pruefstand.report._context import Builder
from pruefstand.report.format import md_escape
from pruefstand.report.labels import ICON_INFO
from pruefstand.report.tables import Block

SEP = "; "


def absolute_line(b: Builder) -> str | None:
    """Return the tier-2 ``Absolute checks:`` line (non-PASS rows, or ``all PASS (n)``)."""
    rows = b.blocks[Block.A]
    if not rows:
        return None
    bad = [r.absolute_item(d) for d in rows if d.status is not GateStatus.PASS]
    if not bad:
        return f"Absolute checks: all PASS ({len(rows)})"
    return b.joined("Absolute checks:", bad)


def informational_lines(b: Builder) -> list[str]:
    """Return the "Informational (does not block)" line and the judge-truncation line."""
    rows = b.blocks[Block.I]
    plain = [d for d in rows if d.metric not in JUDGED_METRICS or b.tier1]
    items = [r.info_item(d) for d in plain]
    if not b.tier1:
        judged = [r.info_item(d) for d in rows if d.metric in JUDGED_METRICS]
        if b.cand.judged_subset:
            items.append(f"{lb.JUDGED_SUBSET}: {SEP.join(judged)}" if judged else lb.JUDGED_SUBSET)
        else:
            items.extend(judged)
    out: list[str] = []
    line = b.joined("Informational (does not block):", items, SEP)
    if line:
        out.append(line)
    cut = b.cand.counts.get("judge_truncated", 0)
    if cut > 0:
        noun = "case" if cut == 1 else "cases"
        out.append(f"Judge input truncated on {cut} {noun}; those judgments may be incomplete.")
    return out


def judged_line(b: Builder) -> str | None:
    """Return the tier-1 judged line, or the skipped notice when the judge did not run."""
    if b.cand.judge_mode == "skipped":
        return f"> {ICON_INFO} {lb.NOTICE_JUDGE_SKIPPED}"
    rows = b.blocks[Block.J]
    if not rows:
        return None
    source = lb.JUDGE_SOURCE[b.cand.judge_mode]
    cases = f"{b.cand.judged_cases} cases"
    if b.cand.judged_subset:
        cases += f", {lb.JUDGED_SUBSET}"
    head = f"**Judged metrics (informational, does not block; {source}, {cases}):**"
    items = [r.info_item(d, reason=False) for d in rows]
    shown = b.cap(items, b.lim.items)
    return f"{head} {' · '.join(shown)}"


def notable_line(b: Builder) -> str | None:
    """Return the notable-slice line (``notable == True`` rows only)."""
    items = [r.notable_item(d) for d in b.blocks[Block.N] if d.notable]
    return b.joined("Notable slice drops (informational):", items)


def cause_line(b: Builder) -> str | None:
    """Return ``Likely cause: <code> — <message>``."""
    code = b.report.likely_cause
    if code is None:
        return None
    message = CAUSE_MESSAGES[code].replace(": <codes>", "")
    return f"Likely cause: {code} — {message}"


def coverage_line(b: Builder, insufficient: list[str]) -> str | None:
    """Return ``Not applicable: ... · Insufficient data: ...`` (each part only when non-empty)."""
    parts: list[str] = []
    counts = b.report.not_applicable_counts
    if counts:
        shown = b.cap(sorted(counts.items()), b.lim.items)
        parts.append(
            "Not applicable: " + ", ".join(f"{md_escape(k)} ({v} cases)" for k, v in shown)
        )
    thin = b.joined("Insufficient data:", insufficient)
    if thin:
        parts.append(thin)
    return " · ".join(parts) or None


def tier2_lines(b: Builder, insufficient: list[str]) -> list[str]:
    """Return the lines below the tables of the tier-2 layout, in ui-spec §12.1 order."""
    out: list[str | None] = []
    if not b.report.no_baseline:
        out = [absolute_line(b), *informational_lines(b), notable_line(b), cause_line(b),
               coverage_line(b, insufficient)]  # fmt: skip
    return [*(x for x in out if x), *_tail(b)]


def tier1_lines(b: Builder, insufficient: list[str]) -> list[str]:
    """Return the lines below the tables of the tier-1 layout, in ui-spec §12.2 order."""
    out: list[str | None] = []
    if not b.report.no_baseline:
        out = [*informational_lines(b), judged_line(b), notable_line(b), cause_line(b),
               coverage_line(b, insufficient)]  # fmt: skip
    return [*(x for x in out if x), *_tail(b)]


def _tail(b: Builder) -> list[str]:
    top = b.top_failing()
    return [top] if top else []
