"""``pruefstand report``: render a gated run as Markdown or JSON, optionally publish it."""

import os
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from pruefstand.cli._common import EXIT_USAGE, fail, guarded, not_implemented
from pruefstand.core.errors import ConfigError, StoreError
from pruefstand.core.logging import get_logger
from pruefstand.core.models.gate import GateReport
from pruefstand.core.models.run import RunManifest
from pruefstand.core.settings import PruefstandSettings
from pruefstand.pipeline._files import read_regular
from pruefstand.pipeline.gate import GATE_FILE
from pruefstand.report.github import GitHubPublisher
from pruefstand.report.markdown import render_pr_comment
from pruefstand.store.artifacts import ArtifactStore

_log = get_logger(__name__)
_MAX_GATE_BYTES = 16 * 1024 * 1024


class Format(StrEnum):
    """``--format``."""

    MD = "md"
    HTML = "html"
    JSON = "json"
    EVIDENCE = "evidence"


def _gate_text(run: Path) -> str:
    path = run / GATE_FILE
    try:
        raw = read_regular(path, _MAX_GATE_BYTES)
    except OSError:
        fail(f"error: {path} not found; run `pruefstand gate` for this run first", EXIT_USAGE)
    if len(raw) > _MAX_GATE_BYTES:
        fail(f"error: {path} is larger than {_MAX_GATE_BYTES} bytes", EXIT_USAGE)
    return raw.decode("utf-8", errors="replace")


def _baseline_manifest(run: Path, report: GateReport) -> RunManifest | None:
    if report.baseline_run_id is None:
        return None
    try:
        return (
            ArtifactStore(run.parent).read_run(run.parent / report.baseline_run_id).results.manifest
        )
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


def register(app: typer.Typer) -> None:
    """Add the ``report`` command to ``app``."""

    @app.command("report")
    def report_command(
        ctx: typer.Context,
        *,
        run: Annotated[Path, typer.Option("--run", help="Run directory with gate.json.")],
        fmt: Annotated[Format, typer.Option("--format", help="md or json (html: T6.4).")],
        publish_pr: Annotated[
            int | None, typer.Option("--publish-pr", min=1, help="Edit the PR comment.")
        ] = None,
    ) -> None:
        """Print the report of a gated run."""
        if fmt in {Format.HTML, Format.EVIDENCE}:
            not_implemented(f"report --format {fmt.value}", "T6.4")
        if publish_pr is not None and fmt is not Format.MD:
            fail("error: --publish-pr needs --format md", EXIT_USAGE)
        with guarded(ctx):
            text = _gate_text(run)
            try:
                report = GateReport.model_validate_json(text)
            except ValidationError:
                fail(f"error: {run / GATE_FILE} is not a valid gate report", EXIT_USAGE)
            if fmt is Format.JSON:
                typer.echo(text.rstrip("\n"))
                return
            candidate = ArtifactStore(run.parent).read_run(run).results.manifest
            body = render_pr_comment(
                report, _baseline_manifest(run, report), candidate, report_url=None
            )
            typer.echo(body.rstrip("\n"))
            if publish_pr is not None:
                _publish(body, publish_pr)
