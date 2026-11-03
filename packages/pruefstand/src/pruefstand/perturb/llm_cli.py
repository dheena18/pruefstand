"""LLM part of ``python -m pruefstand.perturb`` (T4.5): ``--pass rewrite|validate|both``.

Output, one line per perturbation: ``name<TAB>valid=True<TAB>text`` or
``name<TAB>valid=False<TAB>reason=<why><TAB>original``; ``--pass rewrite`` prints
``name<TAB>rewritten`` (or ``pending (quota|budget)``).
"""

import argparse
import logging
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TextIO

from pruefstand.core.config import ModelRef
from pruefstand.core.config_loader import load_config
from pruefstand.core.errors import ConfigError
from pruefstand.core.models.attacks import CanaryRegistry
from pruefstand.llm.budget import Budget
from pruefstand.llm.client import LLMClient
from pruefstand.llm.factory import build_client
from pruefstand.llm.families import family_of
from pruefstand.llm.recorder import CallRecorder
from pruefstand.perturb.batch import (
    Item,
    RewriteStore,
    item_id,
    item_rng,
    rewrite_pass,
    validate_pass,
)
from pruefstand.perturb.llm_base import LLMRewritePerturbation
from pruefstand.perturb.llm_registry import build_llm_perturbation
from pruefstand.perturb.rewriter import LocalTarget, Rewriter, private_text
from pruefstand.perturb.validate import RewriteValidator

ClientFactory = Callable[[str, int | None], LLMClient]
"""``(model id, request cap) -> client``; tests inject loopback clients, the CLI real ones."""


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """Add the options of the LLM perturbations to ``parser``."""
    g = parser.add_argument_group(
        "LLM perturbations (compound_split, register, gender, colloquial)"
    )
    g.add_argument(
        "--questions", type=Path, help="file with one question per line (instead of QUESTION)"
    )
    g.add_argument(
        "--public",
        action="store_true",
        help="questions without a tenant are public (default: private, local model only)",
    )
    g.add_argument("--model", help="rewrite model, github/<pinned datagen model>")
    g.add_argument("--judge-model", help="local judge for the equivalence check, ollama/<tag>")
    g.add_argument(
        "--second-model", help="second GitHub Models model (validator of local rewrites)"
    )
    g.add_argument("--local-model", help="local rewrite model for questions the data guard blocks")
    g.add_argument("--pass", dest="phase", choices=("rewrite", "validate", "both"), default="both")
    g.add_argument(
        "--store", type=Path, help="directory of the rewrite store (passes rewrite/validate)"
    )
    g.add_argument("--max-requests", type=int, help="cap on rewrite-model requests per run")
    g.add_argument("--config", type=Path, help="pruefstand.yaml (provider policy)")
    g.add_argument("--canaries", type=Path, help="canary registry JSON for the data guard")
    g.add_argument("--no-canaries", action="store_true", help="there are no canaries (explicit)")


def config_client_factory(args: argparse.Namespace) -> ClientFactory:
    """Return the factory that builds real clients from ``--config`` and ``--canaries``.

    Raises:
        ConfigError: ``--config`` missing, or neither ``--canaries`` nor ``--no-canaries`` given
            (the data guard fails closed).
    """
    if args.config is None:
        msg = "--config is required to build the model clients"
        raise ConfigError(msg)
    if args.canaries is None and not args.no_canaries:
        msg = "pass --canaries FILE or --no-canaries (the data guard fails closed)"
        raise ConfigError(msg)
    cfg = load_config(args.config)
    canaries = (
        CanaryRegistry.model_validate_json(args.canaries.read_text(encoding="utf-8"))
        if args.canaries
        else CanaryRegistry(canaries=())
    )

    def factory(model: str, max_requests: int | None) -> LLMClient:
        budget = Budget(max_usd=None, max_tokens=None, max_requests=max_requests)
        return build_client(
            cfg, None, budget, CallRecorder(),
            model=ModelRef(id=model, family=family_of(model)), canaries=canaries,
        )  # fmt: skip

    return factory


def _build(
    names: Sequence[str], args: argparse.Namespace, factory: ClientFactory
) -> list[LLMRewritePerturbation]:
    local = None
    if args.local_model:
        local = LocalTarget(factory(args.local_model, None), args.local_model)
    second = (factory(args.second_model, None), args.second_model) if args.second_model else None
    validator = None
    if args.judge_model:
        validator = RewriteValidator(
            factory(args.judge_model, None), args.judge_model, second=second, seed=args.seed
        )
    rewriter = Rewriter(args.model, local)
    return [build_llm_perturbation(n, rewriter, validator) for n in names]


def _line(name: str, source: str, text: str, *, valid: bool, reason: str) -> str:
    if valid:
        return f"{name}\tvalid=True\t{text}"
    return f"{name}\tvalid=False\treason={reason}\t{source}"


async def run(
    questions: Sequence[tuple[str, bool]],
    names: Sequence[str],
    args: argparse.Namespace,
    factory: ClientFactory,
    out: TextIO,
) -> int:
    """Run the chosen pass for the questions.

    ``questions`` are ``(text, private)``: a private question is only ever sent to the local model.
    With ``--questions`` every line starts with the item id (``q`` + content hash).

    Returns:
        0 on success, 3 when the quota or request cap stopped the rewrite.

    Raises:
        LLMError: A model call failed.
    """
    _quiet_provider_logs()
    perturbations = _build(names, args, factory)
    items = [Item(id=item_id(q), text=q, private=private) for q, private in questions]
    texts = {it.id: it.text for it in items}

    def emit(item_id: str, line: str) -> None:
        out.write((f"{item_id}\t" if args.questions else "") + line + "\n")

    if args.phase == "both":
        llm = factory(args.model, args.max_requests)
        for item in items:
            for p in perturbations:
                with private_text(private=item.private):
                    res = await p.aapply(item.text, llm, item_rng(item, p, args.seed))
                emit(
                    item.id, _line(p.name, item.text, res.text, valid=res.changed, reason=res.notes)
                )
        return 0
    store = RewriteStore(args.store)
    if args.phase == "rewrite":
        llm = factory(args.model, args.max_requests)
        report = await rewrite_pass(items, perturbations, llm=llm, store=store, seed=args.seed)
        status = f"pending ({report.stopped})" if report.stopped else "rewritten"
        for p in perturbations:
            out.write(f"{p.name}\t{status}\t{report.done} new, {report.skipped} stored\n")
        return 3 if report.stopped else 0
    for o in await validate_pass(items, perturbations, store=store, seed=args.seed):
        src = texts[o.item_id]
        emit(
            o.item_id,
            _line(o.name, src, o.result.text, valid=o.result.changed, reason=o.result.notes),
        )
    return 0


def usage_problem(args: argparse.Namespace) -> str | None:
    """Return what is wrong with the LLM options of ``args``, or None."""
    if not args.model:
        return "the LLM perturbations need --model (the rewrite model)"
    if args.phase != "rewrite" and not args.judge_model:
        return "the validity check needs --judge-model"
    if args.phase != "both" and args.store is None:
        return f"--pass {args.phase} needs --store"
    return None


def _quiet_provider_logs() -> None:
    """Keep the provider library's INFO lines off stdout, where the result lines go."""
    for name in ("LiteLLM", "LiteLLM Router", "LiteLLM Proxy"):
        logging.getLogger(name).setLevel(logging.WARNING)
