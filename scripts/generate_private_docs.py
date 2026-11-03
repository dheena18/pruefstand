"""Generate DRAFT synthetic private documents with the LOCAL judge model (T2.6 S2).

Run on the VM under the GPU lock, with the day set loaded (no model swap, no ``MAINTENANCE``)::

    pruefstand-lock uv run python scripts/generate_private_docs.py --tenant all --n 8 --seed 7

Private documents and canary facts never leave the machines (ADR-0019, D330): the model must be a
local provider (``ollama/...`` on the A40 server through the tunnel, or ``openai_compatible_local``
llama.cpp) and must not be of the generator family ``qwen`` (AI11-12b). The fact sentence of each
document is built by code (``attacks.facts``); the model writes only the text around it. Drafts go
to the git-ignored ``datasets/private_docs/_drafts/<tenant>/<doc_id>.md``; a person reviews them and
moves the approved ones to ``datasets/private_docs/<tenant>/`` (S5). Re-running skips existing
drafts (resumable); the plan is seeded, the model options come from ``infra/gpu/models.yaml``.

Exit codes: 0 all drafts exist, 1 a draft was rejected or a call failed, 2 refused (model, lock).
"""

import argparse
import asyncio
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from private_doc_plan import (
    LOCAL_PROVIDERS,
    PROMPT_ID,
    PROMPT_VERSION,
    DocPlan,
    DraftRejectedError,
    build_messages,
    check_datagen_model,
    check_output,
    default_model,
    plan_all,
)

from pruefstand.attacks.canary import TENANT_PREFIX
from pruefstand.core.config import LLMPolicyConfig, ModelRef
from pruefstand.core.errors import ConfigError, PruefstandError, StoreError
from pruefstand.core.models.attacks import CanaryRegistry
from pruefstand.core.models.llm import LLMRequest, LLMRole
from pruefstand.ingest.private_docs import render_private_doc
from pruefstand.llm.backends.litellm import LiteLLMBackend  # noqa: F401  (backend of build_backend)
from pruefstand.llm.budget import Budget
from pruefstand.llm.client import LLMClient
from pruefstand.llm.factory import build_backend
from pruefstand.llm.policy import LLMPolicy
from pruefstand.llm.recorder import CallRecorder
from pruefstand.store.canary_source import load_canary_registry

REPO = Path(__file__).resolve().parents[1]
DEFAULT_DRAFTS = REPO / "datasets" / "private_docs" / "_drafts"
MAX_TOKENS = 384  # the catalogue bound of the judge model (option_bounds.num_predict)
DEFAULT_CATALOGUE = REPO / "infra" / "gpu" / "models.yaml"
PROMPTS = REPO / "packages" / "pruefstand" / "src" / "pruefstand" / "attacks" / "prompts"


def make_client(ref: ModelRef, max_requests: int) -> LLMClient:
    """Build the client: local providers only, no cache (private text is never cached)."""
    policy = LLMPolicyConfig(allowed_providers=LOCAL_PROVIDERS)
    try:
        registry = load_canary_registry(root=REPO)
    except StoreError:
        registry = CanaryRegistry(canaries=())
    return LLMClient(
        build_backend(ref, policy=policy),
        None,
        Budget(max_usd=None, max_tokens=None, max_requests=max_requests),
        CallRecorder(), LLMPolicy(policy, registry),
    )  # fmt: skip


async def generate_one(
    client: LLMClient, ref: ModelRef, plan: DocPlan, attempts: int, seed: int
) -> str:
    """Ask the model until an answer passes ``check_output`` (at most ``attempts`` calls).

    Raises:
        DraftRejectedError: Every answer was rejected (the last reason is reported).
    """
    last: DraftRejectedError | None = None
    for attempt in range(attempts):
        request = LLMRequest(
            role=LLMRole.DATAGEN, model=ref.id, messages=build_messages(plan, attempt),
            max_tokens=MAX_TOKENS, seed=seed, prompt_id=PROMPT_ID, prompt_version=PROMPT_VERSION,
        )  # fmt: skip
        response = await client.complete(request)
        try:
            return check_output(response.text, plan)
        except DraftRejectedError as exc:
            last = exc
    assert last is not None  # noqa: S101  (attempts >= 1 is checked by the parser)
    raise last


async def _run(args: argparse.Namespace, ref: ModelRef) -> int:
    tenants = list(TENANT_PREFIX) if args.tenant == "all" else [args.tenant]
    client = make_client(ref, len(tenants) * args.n * args.attempts)
    plans = plan_all(args.n, args.seed)
    failed = 0
    for tenant in tenants:
        for plan in plans[tenant]:
            path = args.drafts / tenant / f"{plan.front.doc_id}.md"
            if path.exists():
                print(f"skip {path.name} (exists)")
                continue
            try:
                body = await generate_one(client, ref, plan, args.attempts, args.seed)
            except DraftRejectedError as exc:
                failed += 1
                print(f"rejected {exc}", file=sys.stderr)
                continue
            heading = body.splitlines()[0].removeprefix("# ").strip()
            front = plan.front.model_copy(update={"title": heading})
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(render_private_doc(front, body), encoding="utf-8")
            print(f"wrote {path.name}")
    return 1 if failed else 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    parser.add_argument("--tenant", choices=[*TENANT_PREFIX, "all"], required=True)
    parser.add_argument("--n", type=int, default=8)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--drafts", type=Path, default=DEFAULT_DRAFTS)
    parser.add_argument("--model", help="default: the catalogue's standard judge model")
    parser.add_argument("--family", help="family of --model (required with --model)")
    parser.add_argument("--catalogue", type=Path, default=DEFAULT_CATALOGUE)
    parser.add_argument("--attempts", type=int, default=3)
    return parser


def _prepare(args: argparse.Namespace) -> ModelRef:
    """Check arguments, model and lock; return the model to use.

    Raises:
        ConfigError: Anything the run must be refused for.
    """
    if args.attempts < 1:
        msg = "--attempts must be at least 1"
        raise ConfigError(msg)
    if bool(args.model) != bool(args.family):
        msg = "--model and --family go together"
        raise ConfigError(msg)
    if args.model:
        ref = ModelRef(id=args.model, family=args.family)
    else:
        ref = default_model(args.catalogue)
    check_datagen_model(ref)
    if os.environ.get("PRUEFSTAND_LOCK_HELD") != "1":
        msg = "run this script under 'pruefstand-lock' (the GPU lock, D212)"
        raise ConfigError(msg)
    return ref


def main(argv: Sequence[str] | None = None) -> int:
    """Run the generator; returns the exit code (see the module docstring)."""
    args = _parser().parse_args(argv)
    try:
        return asyncio.run(_run(args, _prepare(args)))
    except ConfigError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    except PruefstandError as exc:
        print(f"failed: {type(exc).__name__}: {str(exc)[:200]}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
