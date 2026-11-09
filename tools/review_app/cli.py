"""Command line of the review workflow (T4.7a): ``make review-model | review-app | review-summary``.

    PYTHONPATH=tools uv run python -m review_app.cli model --config dataset.yaml
    PYTHONPATH=tools uv run python -m review_app.cli spotcheck|summary|apply --config dataset.yaml

``model`` runs the model review of the built dataset (the reviewer is a local model: run it under
``pruefstand-lock`` on the VM), ``spotcheck`` draws the owner sample, ``summary`` prints the error
rate per stratum, the owner's flag rates and the trust verdict, ``apply`` writes the decisions into
the dataset directory (the only step that does).
"""

import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path

from pruefstand.core.config import DatasetBuildConfig
from pruefstand.core.config_loader import load_model
from pruefstand.core.errors import PruefstandError
from pruefstand.dataset.review import StratumRate
from pruefstand.pipeline.build_clients import BuildClients, default_clients
from pruefstand.pipeline.review_run import (
    apply_review,
    run_model_review,
    summarise,
    write_spotcheck_sample,
)


def _rates(rates: dict[str, StratumRate]) -> list[str]:
    return [
        f"  {r.stratum}: reviewed={r.reviewed} fix={r.fix} reject={r.reject} "
        f"error_rate={r.error_rate:.3f}{' NEEDS_REGENERATION' if r.needs_regeneration else ''}"
        for r in rates.values()
    ]


def run(argv: Sequence[str] | None = None, *, clients: BuildClients | None = None) -> int:
    """Run the command; returns the exit code (0 ok, 2 refused, 3 failed)."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["model", "spotcheck", "summary", "apply"])
    parser.add_argument("--config", type=Path, default=Path("dataset.yaml"))
    args = parser.parse_args(argv)
    try:
        cfg = load_model(args.config, DatasetBuildConfig)
        return _dispatch(args.command, cfg, clients or default_clients(Path.cwd()))
    except PruefstandError as exc:
        print(f"failed: {type(exc).__name__}: {str(exc)[:300]}", file=sys.stderr)
        return 2


def _dispatch(command: str, cfg: DatasetBuildConfig, clients: BuildClients) -> int:
    if command == "model":
        run_ = asyncio.run(run_model_review(cfg, clients))
        print(f"reviewed={run_.reviewed} failed={len(run_.failed)}")
        print("\n".join(_rates(run_.rates)))
        return 3 if run_.failed else 0
    if command == "spotcheck":
        print(f"spotcheck_sample={len(write_spotcheck_sample(cfg))}")
        return 0
    if command == "summary":
        s = summarise(cfg)
        print("model error rate per stratum:")
        print("\n".join(_rates(s.rates)) or "  (no review items yet)")
        print(f"spot-check: checked={s.spot_checked} flagged={s.spot_flagged}")
        print(f"spot-check of model-ok items: checked={s.ok_checked} flagged={s.ok_flagged}")
        verdict = {None: "unknown (no decisions yet)", True: "trusted", False: "NOT trusted"}
        print(f"trust: {verdict[s.trusted]}")
        return 0
    report = apply_review(cfg)
    print(
        f"applied: rejected={report.rejected} fixed={report.fixed} "
        f"variants_dropped={report.variants_dropped} cases={report.cases} rounds={report.rounds}"
    )
    if report.needs_regeneration:
        print("needs regeneration: " + ", ".join(report.needs_regeneration))
    return 0


if __name__ == "__main__":
    sys.exit(run())
