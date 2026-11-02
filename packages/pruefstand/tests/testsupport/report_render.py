"""Shared helpers of the PR-comment tests (T1.9): ``render`` with default manifests."""

from testsupport.report_builders import base_manifest, gate_report, manifest

from pruefstand.core.models.gate import GateReport
from pruefstand.core.models.run import RunManifest
from pruefstand.report.markdown import render_pr_comment

MARKER = "<!-- pruefstand:pr-comment -->"
ROW = "| Context recall | 0.86 | 0.79 | −0.07 (−0.10, −0.04) | 0.05 | 0.04 | FAIL |"
DRIFT = (
    "> ⚠️ Judge drift detected (5 or more of 50 anchor verdicts changed); "
    "judged metrics are informational until the flag clears."
)


def render(
    report: GateReport | None = None,
    cand: RunManifest | None = None,
    base: RunManifest | None = None,
    url: str | None = "https://example.org/r/1",
) -> str:
    """Render ``report`` (default: the FAIL report) with the default manifests."""
    return render_pr_comment(
        report or gate_report(),
        base if base is not None else base_manifest(),
        cand or manifest(),
        report_url=url,
    )


def line_with(text: str, prefix: str) -> str:
    """Return the first line of ``text`` that starts with ``prefix``."""
    return next(line for line in text.splitlines() if line.startswith(prefix))
