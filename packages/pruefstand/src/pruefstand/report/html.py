"""HTML evidence report (ui-spec §13): ``render_html`` fills ``templates/report.html.j2``.

One self-contained file: inline CSS built from ``_tokens.css`` + ``_style.css``, one inline script
(``_sort.js``, table sorting only) and a hash-based Content-Security-Policy ``<meta>`` as the first
child of ``<head>`` (ui-spec §7.4, GitHub Pages sends no headers). Autoescape is on; every
case-, target- or branch-derived string was also cleaned (canaries masked) while the view model was
built. The render is pure: it reads package data only and writes no file.
"""

import base64
import hashlib
import json
from functools import cache
from importlib import resources
from typing import Any

from jinja2 import Environment, PackageLoader, StrictUndefined, Template

from pruefstand.core.models.gate import GateReport
from pruefstand.core.models.run import RunResults
from pruefstand.report._html_view import build_view

_CSP = (
    "default-src 'none'; style-src 'unsafe-inline'; script-src 'sha256-{hash}'; "
    "img-src data:; base-uri 'none'; form-action 'none'"
)


def _asset(name: str) -> bytes:
    return (resources.files("pruefstand.report") / "templates" / name).read_bytes()


@cache
def _template() -> Template:
    env = Environment(
        loader=PackageLoader("pruefstand.report", "templates"),
        autoescape=True,
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    return env.get_template("report.html.j2")


def _licences() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(_asset("_licences.json"))
    return data


def csp_for(script: bytes) -> str:
    """Return the report's policy for an inline ``script`` (its own sha256, base64)."""
    digest = base64.b64encode(hashlib.sha256(script).digest()).decode("ascii")
    return _CSP.format(hash=digest)


def render_html(report: GateReport, base: RunResults | None, cand: RunResults) -> str:
    """Render the single-file HTML report of a gated run.

    Args:
        report: The gate report of the candidate.
        base: Baseline run; ``None`` when there is no baseline or it is not available (the header
            then reads ``Baseline: –`` or the baseline run id, no baseline answers are shown).
        cand: The candidate run. A private render shows chunk text; a ``sanitise_run`` copy has
            none, and the report then contains no chunk text and no canary token.

    Returns:
        A complete HTML document: no external request, no event-handler attribute, the only script
        is ``_sort.js`` byte for byte and the CSP ``<meta>`` carries its hash.
    """
    script = _asset("_sort.js")
    css = (_asset("_tokens.css") + b"\n" + _asset("_style.css")).decode("utf-8")
    context = build_view(report, base, cand)
    context.update(
        csp=csp_for(script),
        css=css,
        script=script.decode("utf-8"),
        licences=_licences(),
    )
    return _template().render(context)
