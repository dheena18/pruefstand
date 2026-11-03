"""``python -m pruefstand.perturb "<question>" --name dates|all|register,colloquial``.

Deterministic names print ``name<TAB>changed|unchanged<TAB>text``. The LLM-assisted names
(``compound_split``, ``register``, ``gender``, ``colloquial``) need ``--model`` and print
``name<TAB>valid=True<TAB>text`` or ``name<TAB>valid=False<TAB>reason=<why><TAB>original``
(see ``llm_cli``).
"""

import argparse
import asyncio
import sys
from collections.abc import Sequence

import numpy as np

from pruefstand.core.errors import ConfigError, LLMError
from pruefstand.perturb import llm_cli
from pruefstand.perturb.llm_registry import llm_perturbation_names
from pruefstand.perturb.registry import get_perturbation, perturbation_names


def _split(names: Sequence[str]) -> tuple[list[str], list[str]]:
    llm = set(llm_perturbation_names())
    return [n for n in names if n not in llm], [n for n in names if n in llm]


def main(
    argv: Sequence[str] | None = None, *, client_factory: llm_cli.ClientFactory | None = None
) -> int:
    """Run the helper.

    Args:
        argv: Arguments (default: ``sys.argv[1:]``).
        client_factory: Builds model clients; default from ``--config`` (tests inject loopback).

    Returns:
        0 on success, 2 for an unknown name or a usage error, 3 when the quota or the request cap
        stopped a rewrite pass, 1 when a model call failed.
    """
    parser = argparse.ArgumentParser(prog="python -m pruefstand.perturb", description=__doc__)
    parser.add_argument("question", nargs="?")
    parser.add_argument(
        "--name", default="all", help="names, comma separated, or all (= the deterministic ones)"
    )
    parser.add_argument("--seed", type=int, default=0, help="seed for the seeded perturbations")
    llm_cli.add_arguments(parser)
    args = parser.parse_args(argv)
    questions = _questions(args)
    if not questions:
        sys.stderr.write("give a QUESTION or --questions FILE\n")
        return 2
    requested = [n for n in args.name.split(",") if n]
    names = list(perturbation_names()) if args.name == "all" else requested
    plain, with_llm = _split(names)
    try:
        chosen = [get_perturbation(n) for n in plain]
    except ConfigError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    for question in questions:
        for p in chosen:
            result = p.apply(question, np.random.default_rng(args.seed))
            status = "changed" if result.changed else "unchanged"
            sys.stdout.write(f"{p.name}\t{status}\t{result.text}\n")
    return _run_llm(args, questions, with_llm, client_factory) if with_llm else 0


def _questions(args: argparse.Namespace) -> list[str]:
    if args.questions is not None:
        lines = args.questions.read_text(encoding="utf-8").splitlines()
        return [ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")]
    return [args.question] if args.question else []


def _run_llm(
    args: argparse.Namespace,
    questions: list[str],
    names: list[str],
    factory: llm_cli.ClientFactory | None,
) -> int:
    problem = llm_cli.usage_problem(args)
    if problem:
        sys.stderr.write(f"{problem}\n")
        return 2
    try:
        make = factory or llm_cli.config_client_factory(args)
        return asyncio.run(llm_cli.run(questions, names, args, make, sys.stdout))
    except ConfigError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    except LLMError as exc:
        sys.stderr.write(f"model call failed: {type(exc).__name__}: {str(exc)[:200]}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
