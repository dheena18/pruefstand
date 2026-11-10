"""``pruefstand baseline``: promote, export-public, prune, publish-dashboard, fingerprint-check."""

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from pruefstand.cli._common import EXIT_FAIL, EXIT_USAGE, fail, guarded
from pruefstand.core.config import GatePolicy
from pruefstand.core.config_loader import load_config
from pruefstand.core.errors import GateInputError
from pruefstand.core.protocols import BaselineStore
from pruefstand.gate.baseline_run import check_baseline_run
from pruefstand.metrics.registry import MetricRegistry
from pruefstand.pipeline.baseline_fingerprint import check_baseline_fingerprint
from pruefstand.pipeline.promotion import check_gate_for_promotion
from pruefstand.store.artifacts import ArtifactStore
from pruefstand.store.baseline_index import REFS
from pruefstand.store.baselines_git import GitBranchBaselineStore
from pruefstand.store.baselines_local import LocalDirBaselineStore
from pruefstand.store.canary_source import load_canary_registry
from pruefstand.store.dashboard_repo import push_dashboard_data
from pruefstand.store.factory import build_baseline_store
from pruefstand.store.promote import BaselineRefused, prepare_promotion
from pruefstand.store.sanitise import sanitise_run, write_public_export

_REPO = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*")
_Run = Annotated[Path, typer.Option("--run", help="Run directory runs/<id>.")]
_Config = Annotated[
    Path,
    typer.Option(
        "--config", envvar="PRUEFSTAND_CONFIG", help="pruefstand.yaml (its baseline_store is used)."
    ),
]


def _informational_metrics(stack: str, ref: str, policy: GatePolicy) -> frozenset[str]:
    """Metrics the gate treats as informational against this baseline (not checked at promote).

    Tier 1 (``live``): every paired metric. Ref ``main`` (PR runs): ``refusal_correct``, which is
    gated only in the nightly ``full`` runs (``nightly-b*``, ``release-b*``).
    """
    if stack == "live":
        return frozenset(policy.metrics)
    return frozenset({"refusal_correct"}) if ref == "main" else frozenset()


def promote_command(
    ctx: typer.Context,
    *,
    run: _Run,
    ref: Annotated[str, typer.Option("--ref", help=f"One of: {', '.join(REFS)}.")],
    config: _Config = Path("pruefstand.yaml"),
    allow_failed_gate: Annotated[
        bool,
        typer.Option(
            "--allow-failed-gate",
            help="Promote although the gate FAILed or the run has hard fails (owner only).",
        ),
    ] = False,
) -> None:
    """Promote a complete run to the baseline of its fingerprint and ref.

    main and nightly runs need their gate.json (run `pruefstand gate` first); a run whose gate
    FAILed or that has a hard-fail finding is refused (exit 1) unless --allow-failed-gate is
    given; an invalid gate.json is exit 3 (D881).
    """
    with guarded(ctx):
        artifacts = ArtifactStore(run.parent).read_run(run)
        cfg = load_config(config)
        try:
            prepared = prepare_promotion(artifacts, ref)
            check_gate_for_promotion(
                run, artifacts.results, cfg.gate, ref=ref, allow_failed_gate=allow_failed_gate
            )
            check_baseline_run(
                prepared.results,
                cfg.gate,
                MetricRegistry.full().directions(),
                skip=_informational_metrics(prepared.results.manifest.stack, ref, cfg.gate),
            )
            build_baseline_store(cfg.baseline_store).put(prepared, ref)
        except BaselineRefused as exc:
            fail(f"error: {exc}", EXIT_FAIL)
        except GateInputError as exc:
            fail(
                f"error: not promoted, the gate could not judge this run as a baseline: {exc}",
                EXIT_FAIL,
            )
        manifest = prepared.results.manifest
        typer.echo(f"promoted {manifest.run_id} to {manifest.eval_fingerprint}/{ref}")


def export_public_command(
    ctx: typer.Context,
    *,
    run: _Run,
    out: Annotated[Path, typer.Option("--out", help="New directory for the public copy.")],
) -> None:
    """Write a sanitised copy of a run (no chunk text, no canaries) for the public repo."""
    with guarded(ctx):
        artifacts = ArtifactStore(run.parent).read_run(run)
        clean = sanitise_run(artifacts, load_canary_registry())
        typer.echo(str(write_public_export(clean, out)))


def _prunable(store: BaselineStore) -> LocalDirBaselineStore | GitBranchBaselineStore:
    if not isinstance(store, LocalDirBaselineStore | GitBranchBaselineStore):
        fail("error: this baseline store cannot be pruned", EXIT_USAGE)
    return store


def prune_command(
    ctx: typer.Context,
    *,
    keep: Annotated[
        int, typer.Option("--keep", min=1, help="History entries per fingerprint.")
    ] = 20,
    unused_days: Annotated[
        int, typer.Option("--unused-days", min=0, help="Drop fingerprints unused this long.")
    ] = 90,
    config: _Config = Path("pruefstand.yaml"),
) -> None:
    """Delete old baselines (last N per fingerprint) and unused fingerprints."""
    with guarded(ctx):
        store = _prunable(build_baseline_store(load_config(config).baseline_store))
        removed = store.prune(keep=keep, unused_days=unused_days, now=datetime.now(UTC))
        for item in removed:
            typer.echo(f"removed {item}")
        typer.echo(f"{len(removed)} removed")


def publish_command(
    ctx: typer.Context,
    *,
    src: Annotated[Path, typer.Option("--src", help="Sanitised export directory.")],
    repo: Annotated[str, typer.Option("--repo", help="owner/pruefstand-dashboard-data.")],
) -> None:
    """Push a sanitised export to the public dashboard-data repo (token: DASHBOARD_DATA_PAT)."""
    if _REPO.fullmatch(repo) is None:
        fail("error: --repo must be owner/name", EXIT_USAGE)
    with guarded(ctx):
        typer.echo(push_dashboard_data(src, repo))


def fingerprint_check_command(
    ctx: typer.Context,
    *,
    candidate: Annotated[Path, typer.Option("--candidate", help="Candidate run directory.")],
    baseline: Annotated[Path, typer.Option("--baseline", help="Baseline run directory.")],
) -> None:
    """Print ``comparable``, ``changed <baseline fp> <candidate fp>`` or ``unreadable``; exit 0.

    Tells the tier-1 workflow whether the loaded baseline can be paired with the candidate (D1000).
    It never decides pass or fail; an unreadable candidate exits 3.
    """
    with guarded(ctx):
        check = check_baseline_fingerprint(candidate, baseline)
    if check.comparable:
        typer.echo("comparable")
    elif not check.baseline:
        typer.echo("unreadable")
    else:
        typer.echo(f"changed {check.baseline[:12]} {check.candidate[:12]}")


def register(app: typer.Typer) -> None:
    """Add the ``baseline`` command group to ``app``."""
    baseline = typer.Typer(help="Baseline store, sanitised export and dashboard data (T6.1).")
    baseline.command("promote")(promote_command)
    baseline.command("export-public")(export_public_command)
    baseline.command("prune")(prune_command)
    baseline.command("fingerprint-check")(fingerprint_check_command)
    baseline.command("publish-dashboard")(publish_command)
    app.add_typer(baseline, name="baseline")
