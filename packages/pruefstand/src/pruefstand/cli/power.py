"""``pruefstand power``: power and minimum detectable effect from ``gate.stats`` (D56)."""

import math
from typing import Annotated

import typer

from pruefstand.cli._common import EXIT_USAGE, fail
from pruefstand.core.errors import GateInputError
from pruefstand.gate.stats import minimum_detectable_effect, power_estimate


def register(app: typer.Typer) -> None:
    """Add the ``power`` command to ``app``."""

    @app.command("power")
    def power_command(
        *,
        sigma: Annotated[float, typer.Option("--sigma", help="SD of one per-cluster difference.")],
        n: Annotated[int, typer.Option("--n", help="Number of clusters.")],
        delta: Annotated[float, typer.Option("--delta", help="Relevance threshold max_drop.")],
        alpha: Annotated[float, typer.Option("--alpha", help="One-sided level.")] = 0.025,
        m: Annotated[int, typer.Option("--m", help="Size of the Holm family.")] = 1,
        true_drop: Annotated[
            float | None, typer.Option("--true-drop", help="True drop (default 2 * delta).")
        ] = None,
    ) -> None:
        """Print ``power=<p> mde=<x>`` for a gated metric with n clusters."""
        try:
            power = power_estimate(sigma, n, delta, alpha, m, true_drop=true_drop)
            mde = minimum_detectable_effect(sigma / math.sqrt(n), alpha, delta, m=m)
        except (GateInputError, OverflowError, ValueError) as exc:
            fail(f"error: {exc}", EXIT_USAGE)
        typer.echo(f"power={power:.3f} mde={mde:.4f}")
