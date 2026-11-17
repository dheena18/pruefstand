"""Plan the runs of one noise arm (T6.3 S1).

Usage::

    uv run python experiments/noise/run_noise.py --mode noop --noop-kind reindex --repeats 2
    uv run python experiments/noise/run_noise.py --mode churn --churn-kind temp03 --repeats 2
    uv run python experiments/noise/run_noise.py --mode repeats --repeats 5 --cache-mode off

Writes ``runs/noise/<arm>/plan.json`` and one ``rag.<label>.yaml`` per run (the reference ``main``
run first). The runs themselves go through the tier-2 stack runner of T6.2b under
``pruefstand-lock``; this script only fixes what each run is (``noop.py``).
"""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

import yaml

# run as a script: import noise.* and (through noise.noop) mutations.*
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "benchmarks"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from noise.noop import KINDS, CacheMode, Mode, PlannedRun, build_plan

from pruefstand.core.errors import ConfigError

OUT = Path("runs/noise")


def arm_name(mode: Mode, kind: str | None, cache_mode: CacheMode) -> str:
    """The directory name of an arm, e.g. ``noop_reindex`` or ``repeats_off``."""
    return f"{mode}_{kind or cache_mode}"


def write_plan(out: Path, runs: Sequence[PlannedRun]) -> Path:
    """Write ``plan.json`` and one ``rag.<label>.yaml`` per run into ``out``; return the plan."""
    out.mkdir(parents=True, exist_ok=True)
    for run in runs:
        text = yaml.safe_dump(run.config, sort_keys=False, allow_unicode=True)
        (out / f"rag.{run.label}.yaml").write_text(text, encoding="utf-8")
    plan = out / "plan.json"
    rows = [run.model_dump(mode="json", exclude={"config"}) for run in runs]
    plan.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    return plan


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--mode", choices=["repeats", "noop", "churn"], required=True)
    parser.add_argument("--noop-kind", choices=KINDS["noop"])
    parser.add_argument("--churn-kind", choices=KINDS["churn"])
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--cache-mode", choices=["production", "off"], default="production")
    parser.add_argument("--seed", type=int, default=1234)
    parser.add_argument("--out", type=Path, default=OUT)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Build and write the plan of one arm; 2 on a refused combination."""
    args = _parser().parse_args(argv)
    kind = args.noop_kind if args.mode == "noop" else args.churn_kind
    if args.noop_kind and args.churn_kind:
        kind = "both"  # refused by build_plan
    try:
        runs = build_plan(
            args.mode, kind, repeats=args.repeats, cache_mode=args.cache_mode, seed=args.seed
        )
    except ConfigError as err:
        print(f"error: {err}", file=sys.stderr)
        return 2
    plan = write_plan(args.out / arm_name(args.mode, kind, args.cache_mode), runs)
    print(f"{plan}: {len(runs)} runs ({runs[0].label} + {len(runs) - 1} {args.mode})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
