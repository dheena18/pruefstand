"""``pruefstand report``: render a gated run as Markdown, JSON, HTML or an evidence record."""

import os
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from pruefstand.cli._common import EXIT_USAGE, fail, guarded
from pruefstand.cli._report_files import (
    EVIDENCE_FILE,
    HTML_FILE,
    evidence_json,
    write_atomic,
)
from pruefstand.core.errors import ConfigError, StoreError
from pruefstand.core.logging import get_logger
from pruefstand.core.models.gate import GateReport
from pruefstand.core.models.run import RunResults
from pruefstand.core.settings import PruefstandSettings
from pruefstand.pipeline._files import read_regular
from pruefstand.pipeline.gate import GATE_FILE
from pruefstand.report.github import GitHubPublisher
from pruefstand.report.html import render_html
from pruefstand.report.markdown import render_pr_comment
from pruefstand.report.truncation import judge_truncated_case_ids
from pruefstand.store.artifacts import ArtifactStore

_log = get_logger(__name__)
_MAX_GATE_BYTES = 16 * 1024 * 1024


class Format(StrEnum):
    """``--format``."""

    MD = "md"
    HTML = "html"
    JSON = "json"
    EVIDENCE = "evidence"


def _gate_bytes(run: Path) -> bytes:
    path = run / GATE_FILE
    try:
        raw = read_regular(path, _MAX_GATE_BYTES)
    except OSError:
        fail(f"error: {path} not found; run `pruefstand gate` for this run first", EXIT_USAGE)
    if len(raw) > _MAX_GATE_BYTES:
        fail(f"error: {path} is larger than {_MAX_GATE_BYTES} bytes", EXIT_USAGE)
    return raw


def _baseline_results(run: Path, report: GateReport) -> RunResults | None:
    if report.baseline_run_id is None:
        return None
    try:
        return ArtifactStore(run.parent).read_run(run.parent / report.baseline_run_id).results
    except StoreError:
        _log.warning("baseline_run_unavailable", run_id=report.baseline_run_id)
        return None


def _publish(body: str, pr: int) -> None:
    token = PruefstandSettings().github_token
    repo = os.environ.get("GITHUB_REPOSITORY")
    if token is None or not repo:
        msg = "--publish-pr needs GITHUB_TOKEN and GITHUB_REPOSITORY in the environment"
        raise ConfigError(msg)
    try:
        publisher = GitHubPublisher(token.get_secret_value(), repo)
        publisher.upsert_pr_comment(pr, body, body.splitlines()[0])
    except ValueError as exc:
        msg = f"cannot publish: {exc}"
        raise ConfigError(msg) from None


def _write_file(
    run: Path, fmt: Format, report: GateReport, raw: bytes, config: Path | None
) -> None:
    """Write ``report.html`` or ``evidence.json`` into the run directory and print its path."""
    if fmt is Format.HTML:
        cand = ArtifactStore(run.parent).read_run(run).results
        target, text = run / HTML_FILE, render_html(report, _baseline_results(run, report), cand)
    else:
        if config is None:
            fail("error: --format evidence needs --config <pruefstand.yaml>", EXIT_USAGE)
        target, text = run / EVIDENCE_FILE, evidence_json(run, report, raw, config)
    write_atomic(target, text)
    typer.echo(str(target))


def register(app: typer.Typer) -> None:
    """Add the ``report`` command to ``app``."""

    @app.command("report")
    def report_command(
        ctx: typer.Context,
        *,
        run: Annotated[Path, typer.Option("--run", help="Run directory with gate.json.")],
        fmt: Annotated[Format, typer.Option("--format", help="md, json, html or evidence.")],
        publish_pr: Annotated[
            int | None, typer.Option("--publish-pr", min=1, help="Edit the PR comment.")
        ] = None,
        config: Annotated[
            Path | None, typer.Option("--config", help="pruefstand.yaml (required for evidence).")
        ] = None,
    ) -> None:
        """Print or write the report of a gated run (html and evidence write into the run dir)."""
        if publish_pr is not None and fmt is not Format.MD:
            fail("error: --publish-pr needs --format md", EXIT_USAGE)
        if fmt is Format.EVIDENCE and config is None:
            fail("error: --format evidence needs --config <pruefstand.yaml>", EXIT_USAGE)
        with guarded(ctx):
            raw = _gate_bytes(run)
            text = raw.decode("utf-8", errors="replace")
            try:
                report = GateReport.model_validate_json(text)
            except ValidationError:
                fail(f"error: {run / GATE_FILE} is not a valid gate report", EXIT_USAGE)
            if fmt is Format.JSON:
                typer.echo(text.rstrip("\n"))
            elif fmt in {Format.HTML, Format.EVIDENCE}:
                _write_file(run, fmt, report, raw, config)
            else:
                base = _baseline_results(run, report)
                results = ArtifactStore(run.parent).read_run(run).results
                body = render_pr_comment(
                    report,
                    None if base is None else base.manifest,
                    results.manifest,
                    report_url=None,
                    truncated_cases=judge_truncated_case_ids(results),
                )
                typer.echo(body.rstrip("\n"))
                if publish_pr is not None:
                    _publish(body, publish_pr)
