"""Table builders of the HTML report (ui-spec §11.1 blocks, §13): plain dicts for the template.

A table is ``{"caption", "cols", "rows", "sortable", "note"}``; a row is
``{"cls", "key", "cells"}``;
a cell is ``{"t", "num", "mono", "lang", "sort"}``. Every string passes ``clean`` here; the
template escapes it again on output (autoescape) and never sees a raw value. No number is computed:
all of them come from ``SliceDecision`` / ``BootstrapResult``.
"""

from collections.abc import Sequence
from typing import Any

from pruefstand.core.enums import GateStatus
from pruefstand.core.models.gate import HardFailFinding, SliceDecision
from pruefstand.report._html_text import clean
from pruefstand.report.format import DASH, fmt_delta, fmt_num, fmt_signed
from pruefstand.report.labels import METRIC_LABELS, REASON_LABELS
from pruefstand.report.tables import NO_REASON

OVERALL = "overall"
MAX_ROWS = 1000
STATUS: dict[GateStatus, tuple[str, str, str]] = {
    GateStatus.PASS: ("s-pass", "✅", "PASS"),
    GateStatus.WARN: ("s-warn", "⚠️", "WARN"),
    GateStatus.UNSUPPORTED_CONFIG: ("s-warn", "⚠️", "UNSUPPORTED"),
    GateStatus.FAIL: ("s-fail", "❌", "FAIL"),
    GateStatus.INSUFFICIENT_DATA: ("s-insufficient", "◌", "INSUFFICIENT"),
}
Cell = dict[str, Any]
Row = dict[str, Any]
Table = dict[str, Any]


def cell(
    text: str,
    *,
    num: bool = False,
    mono: bool = False,
    lang: str | None = None,
    sort: str | None = None,
    cls: str | None = None,
) -> Cell:
    """Return one cell (``text`` is already clean)."""
    return {"t": text, "num": num, "mono": mono, "lang": lang, "sort": sort, "cls": cls}


def status_cell(status: GateStatus) -> Cell:
    """Return icon + word (status never rests on colour alone)."""
    cls, icon, word = STATUS[status]
    return cell(f"{icon} {word}", cls=cls, sort=word)


def table(
    caption: str,
    cols: Sequence[tuple[str, bool]],
    rows: Sequence[Row],
    *,
    sortable: bool = False,
    note: str | None = None,
) -> Table:
    """Return a table; ``cols`` holds ``(label, numeric)``. Rows beyond ``MAX_ROWS`` are cut."""
    shown = list(rows[:MAX_ROWS])
    cut = len(rows) - len(shown)
    notes = [n for n in (note, f"{cut} more rows not shown." if cut else None) if n]
    return {
        "caption": caption,
        "cols": [{"label": label, "num": num} for label, num in cols],
        "rows": shown,
        "sortable": sortable,
        "note": " ".join(notes) or None,
    }


def row(*cells: Cell, key: str | None = None, cls: str | None = None) -> Row:
    """Return a row; ``key`` marks the ``SliceDecision`` it shows (accounting in the tests)."""
    return {"cells": list(cells), "key": key, "cls": cls}


def label(metric: str) -> str:
    """Return the en label of ``metric``; an unknown name is cleaned and shown raw."""
    return METRIC_LABELS.get(metric) or clean(metric, 80)


def reason(code: str | None) -> str:
    """Return the label of an informational reason; unknown codes are shown raw, none as ``–``."""
    if code is None or code == NO_REASON:
        return DASH
    return REASON_LABELS.get(code) or clean(code, 80)


def slice_text(d: SliceDecision) -> str:
    """Return ``dimension=value`` (cleaned)."""
    return f"{clean(d.dimension, 60)}={clean(d.value, 80)}"


def decision_key(d: SliceDecision) -> str:
    """Return the identity of a decision inside one report."""
    return f"{clean(d.metric, 60)}|{clean(d.dimension, 60)}|{clean(d.value, 80)}"


def delta(d: SliceDecision) -> str:
    """Return ``Δ (low, high)`` from the bootstrap result, or ``–``."""
    r = d.result
    return DASH if r is None else fmt_delta(r.mean_diff, r.ci_low, r.ci_high)


def _num(value: float | None) -> Cell:
    return cell(fmt_num(value), num=True, sort="" if value is None else f"{value:.6f}")


def _diff(d: SliceDecision) -> Cell:
    text = DASH if d.result is None else fmt_signed(d.result.mean_diff)
    return cell(text, num=True, sort=None if d.result is None else f"{d.result.mean_diff:.6f}")


def gated_row(d: SliceDecision, *, with_slice: bool) -> Row:
    """Return a block-G row: [Slice |] Metric | Base | PR | Δ (95% CI) | δ | MDE | Status."""
    cells = [cell(label(d.metric)), _num(d.baseline_mean), _num(d.candidate_mean)]
    cells += [cell(delta(d), num=True, sort=_diff(d)["sort"]), _num(d.max_drop), _num(d.mde)]
    cells.append(status_cell(d.status))
    if with_slice:
        cells.insert(0, cell(slice_text(d)))
    dim = d.status is GateStatus.INSUFFICIENT_DATA
    return row(*cells, key=decision_key(d), cls="dim" if dim else None)


def check_row(d: SliceDecision) -> Row:
    """Return a block A / C row: Metric | Value | Max | Status."""
    name = label(d.metric) if d.dimension == OVERALL else f"{label(d.metric)} · {slice_text(d)}"
    return row(
        cell(name), _num(d.candidate_mean), _num(d.max_value), status_cell(d.status),
        key=decision_key(d),
    )  # fmt: skip


def reported_row(d: SliceDecision) -> Row:
    """Return a block-R row (no status word): Metric, Base, PR, Δ, MDE, Max, Reported because."""
    name = label(d.metric) if d.dimension == OVERALL else f"{label(d.metric)} · {slice_text(d)}"
    return row(
        cell(name), _num(d.baseline_mean), _num(d.candidate_mean), _diff(d), _num(d.mde),
        _num(d.max_value), cell(reason(d.informational_reason)), key=decision_key(d),
    )  # fmt: skip


def info_row(d: SliceDecision) -> Row:
    """Return a block-I row (no status word): Metric | Base | PR | Δ | Reason."""
    name = label(d.metric) if d.dimension == OVERALL else f"{label(d.metric)} · {slice_text(d)}"
    return row(
        cell(name), _num(d.baseline_mean), _num(d.candidate_mean), _diff(d),
        cell(reason(d.informational_reason)), key=decision_key(d),
    )  # fmt: skip


def judged_row(d: SliceDecision, judged_cases: int) -> Row:
    """Return a block-J row: Metric | Base | PR | Δ | Judged cases."""
    name = label(d.metric) if d.dimension == OVERALL else f"{label(d.metric)} · {slice_text(d)}"
    return row(
        cell(name), _num(d.baseline_mean), _num(d.candidate_mean), _diff(d),
        cell(str(judged_cases), num=True), key=decision_key(d),
    )  # fmt: skip


def notable_row(d: SliceDecision) -> Row:
    """Return a block-N row: Slice | Metric | Base | PR | Δ | Notable (marker word, not colour)."""
    mark = "notable" if d.notable else DASH
    return row(
        cell(slice_text(d)), cell(label(d.metric)), _num(d.baseline_mean),
        _num(d.candidate_mean), _diff(d), cell(mark), key=decision_key(d),
    )  # fmt: skip


def hard_fail_row(f: HardFailFinding) -> Row:
    """Return a hard-fail row: Rule | Case | Metric | Evidence (redacted, ``lang="de"``)."""
    name = METRIC_LABELS.get(f.metric) or clean(f.metric, 60)
    rule = name if f.rule == "hard_fail" else f"{name} (unverifiable)"
    return row(
        cell(rule), cell(clean(f.case_id, 80), mono=True), cell(clean(f.metric, 60), mono=True),
        cell(clean(f.evidence, 200), lang="de"),
    )  # fmt: skip
