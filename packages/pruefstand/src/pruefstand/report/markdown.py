"""PR comment renderer (ui-spec §12): ``render_pr_comment`` fills ``templates/pr_comment.md.j2``.

The template is layout only. Every untrusted string is neutralised while the view model is built
(``_context.py``); this module renders, enforces the 60 000-character cap and normalises blank
lines. Rendering is linear in the size of the report.
"""

import re
from functools import cache
from typing import Any

from jinja2 import Environment, PackageLoader, StrictUndefined, Template

from pruefstand.core.models.gate import GateReport
from pruefstand.core.models.run import RunManifest
from pruefstand.report._context import FULL, MINIMAL, TIGHT, Builder, Limits
from pruefstand.report._lines import tier1_lines, tier2_lines

MAX_CHARS = 60_000
TRUNCATION_NOTE = "… truncated, see full report"
_STEPS = (FULL, TIGHT, MINIMAL)
_BLANKS = re.compile(r"\n{3,}")


@cache
def _template() -> Template:
    env = Environment(
        loader=PackageLoader("pruefstand.report", "templates"),
        autoescape=False,  # noqa: S701  (Markdown, not HTML; md_escape handles every string)
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=False,
    )
    return env.get_template("pr_comment.md.j2")


def _context(
    report: GateReport, base: RunManifest | None, cand: RunManifest, url: str | None, lim: Limits
) -> dict[str, Any]:
    b = Builder(report, base, cand, url, lim)
    overall, slices, thin = b.gated_tables()
    lines = (tier1_lines if b.tier1 else tier2_lines)(b, thin)
    return {
        "marker": b.marker,
        "title": b.title(),
        "refs": b.refs(),
        "notices": b.notices(),
        "hard_fails": b.hard_fails(),
        "checks": b.checks(),
        "tables": [t for t in (overall, slices, b.reported()) if t is not None],
        "lines": lines,
        "footer": b.footer(),
        "truncated": b.truncated,
    }


def _normalise(text: str) -> str:
    return _BLANKS.sub("\n\n", text).strip() + "\n"


def _hard_cut(text: str) -> str:
    """Last resort: cut at the cap, close open ``<details>`` and end with the truncation note."""
    keep = text[: MAX_CHARS - 200]
    keep = keep[: keep.rfind("\n")] if "\n" in keep else keep
    closing = "\n</details>" * max(0, keep.count("<details>") - keep.count("</details>"))
    return f"{keep}{closing}\n\n{TRUNCATION_NOTE}\n"


def render_pr_comment(
    report: GateReport, base: RunManifest | None, cand: RunManifest, *, report_url: str | None
) -> str:
    """Render the PR comment for ``report`` (ui-spec §12.1 tier 2, §12.2 tier 1).

    The tier follows ``cand.stack`` (``a40`` tier 2, ``live`` tier 1). Everything the target
    controls is escaped: no raw HTML, mentions, links or images reach the comment, and it never
    holds chunk text or a canary token. At most 60 000 characters: when the first pass is longer
    the slice and list sections shrink step by step and the comment ends with a truncation note.

    Args:
        report: The gate report.
        base: Baseline manifest; ``None`` when there is no baseline or it is not available (the
            refs line then reads ``Baseline: –`` or the baseline run id).
        cand: Candidate manifest.
        report_url: Link to the full report; only ``http(s)`` URLs without white space or ``<>``
            are used, otherwise the private-run note is shown.

    Returns:
        Markdown whose first line is the hidden marker ``<!-- pruefstand:pr-comment -->``.
    """
    template = _template()
    text = ""
    for lim in _STEPS:
        text = _normalise(template.render(_context(report, base, cand, report_url, lim)))
        if len(text) <= MAX_CHARS:
            return text
    return _hard_cut(text)
