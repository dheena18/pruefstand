"""RQ3 A/A replay arm, command line (T7.2 S3b).

Usage::

    uv run python experiments/rq3/replay_cli.py --baseline <run dir> --n 500 --seed 1234 --arm noop

Reads the measured sigma_d of the arm (``noop`` = the primary false-alarm arm, ``churn``) from
T6.3's ``results/noise/mde.csv`` (columns ``metric``, ``slice``, ``sigma_d_noop``,
``sigma_d_churn``; the ``overall`` rows), draws ``n`` mean-zero A/A pairs from the baseline run with
``noise.replay.aa_pair``, decides each with the three variants and appends one row per variant to
``results/rq3/replay.csv``, with the commit SHA of ``PREREGISTRATION.md`` (§ "Pre-registration").
"""

import argparse
import csv
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

import numpy as np

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1])
)  # run as a script: import rq3.*, noise.*

from noise.replay import aa_pair
from rq3.replay import ArmResult, replay_arm

from pruefstand.core.config_loader import load_config
from pruefstand.core.errors import ConfigError
from pruefstand.core.models.run import RunResults
from pruefstand.metrics.registry import MetricRegistry
from pruefstand.store.artifacts import ArtifactStore

REPO = Path(__file__).resolve().parents[2]
PREREG = "experiments/rq3/PREREGISTRATION.md"
Arm = Literal["noop", "churn"]
COLUMNS = ["prereg_sha", "arm", "variant", "n", "fail", "fail_ci_low", "fail_ci_high",
           "warn_or_fail", "warn_or_fail_ci_low", "warn_or_fail_ci_high"]  # fmt: skip


def load_sigma(path: Path, arm: Arm) -> dict[str, float]:
    """The ``overall`` sigma_d of every metric for ``arm`` from T6.3's ``mde.csv``.

    Raises:
        ConfigError: the file has no ``sigma_d_<arm>`` column or no ``overall`` row.
    """
    column = f"sigma_d_{arm}"
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows or column not in rows[0]:
        msg = f"{path}: no column {column}"
        raise ConfigError(msg)
    sigma = {r["metric"]: float(r[column]) for r in rows if r.get("slice") == "overall"}
    if not sigma:
        msg = f"{path}: no overall rows"
        raise ConfigError(msg)
    return sigma


def prereg_sha(repo: Path = REPO) -> str:
    """The commit SHA of the last change to ``PREREGISTRATION.md`` (recorded in every output)."""
    done = subprocess.run(  # noqa: S603  (fixed git argv)
        ["git", "log", "-1", "--format=%H", "--", PREREG],  # noqa: S607  (git from PATH)
        cwd=repo, capture_output=True, text=True, check=True, timeout=60,
    )  # fmt: skip
    return done.stdout.strip()


def write_rows(path: Path, sha: str, arm: Arm, results: Sequence[ArmResult]) -> None:
    """Append one row per variant to ``path`` (header written for a new file)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        if new:
            writer.writerow(COLUMNS)
        for r in results:
            row = [sha, arm, r.variant, r.n, r.fail, *r.fail_ci, r.warn_or_fail, *r.warn_or_fail_ci]
            writer.writerow(row)


def main(argv: Sequence[str] | None = None) -> int:
    """Run one replay arm and append its rows; returns the exit code."""
    parser = argparse.ArgumentParser(description="RQ3 A/A replay arm (T7.2 S3b)")
    parser.add_argument(
        "--baseline", type=Path, required=True, help="run directory of the main baseline"
    )
    parser.add_argument("--n", type=int, default=500)
    parser.add_argument("--seed", type=int, default=1234)
    parser.add_argument("--arm", choices=["noop", "churn"], required=True)
    parser.add_argument("--sigma-csv", type=Path, default=REPO / "results/noise/mde.csv")
    parser.add_argument("--config", type=Path, default=REPO / "pruefstand.yaml")
    parser.add_argument("--out", type=Path, default=REPO / "results/rq3/replay.csv")
    args = parser.parse_args(argv)
    if args.n < 500:
        print("warning: fewer than the pre-registered 500 pairs", file=sys.stderr)
    baseline = ArtifactStore(args.baseline.parent).read_run(args.baseline).results
    sigma = load_sigma(args.sigma_csv, args.arm)
    policy = load_config(args.config).gate
    directions = MetricRegistry.full().directions()

    def pairs(rng: np.random.Generator) -> tuple[RunResults, RunResults]:
        return aa_pair(baseline, sigma, rng)

    results = replay_arm(pairs, policy, directions=directions, n=args.n, seed=args.seed)
    write_rows(args.out, prereg_sha(), args.arm, results)
    for r in results:
        print(f"{args.arm} {r.variant}: FAIL {r.fail}/{r.n}, WARN-or-FAIL {r.warn_or_fail}/{r.n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
