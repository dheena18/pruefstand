"""``python -m pruefstand.perturb "<question>" --name dates|all`` prints the perturbed text.

Output: one line per perturbation, ``name<TAB>changed|unchanged<TAB>text``.
"""

import argparse
import sys
from collections.abc import Sequence

import numpy as np

from pruefstand.core.errors import ConfigError
from pruefstand.perturb.registry import get_perturbation, perturbation_names


def main(argv: Sequence[str] | None = None) -> int:
    """Run the helper.

    Args:
        argv: Arguments (default: ``sys.argv[1:]``).

    Returns:
        0 on success, 2 for an unknown perturbation name.
    """
    parser = argparse.ArgumentParser(prog="python -m pruefstand.perturb", description=__doc__)
    parser.add_argument("question")
    parser.add_argument("--name", default="all", help="a perturbation name or all")
    parser.add_argument("--seed", type=int, default=0, help="seed for the seeded perturbations")
    args = parser.parse_args(argv)
    names = perturbation_names() if args.name == "all" else (args.name,)
    try:
        chosen = [get_perturbation(n) for n in names]
    except ConfigError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    for p in chosen:
        result = p.apply(args.question, np.random.default_rng(args.seed))
        status = "changed" if result.changed else "unchanged"
        sys.stdout.write(f"{p.name}\t{status}\t{result.text}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
