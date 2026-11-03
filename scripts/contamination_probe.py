"""Report-only contamination probe: does a model know retired canaries closed-book? (T4.6 S7).

Run on the VM under the GPU lock::

    pruefstand-lock uv run python scripts/contamination_probe.py \
        --model ollama/<tag> --family <family>

Every retired *semantic* canary of ``datasets/canaries/retired.json`` is asked as its
``probe_question`` directly at the model, without retrieval. A match of the canary's
``forbidden_answer`` means the model saw published Prüfstand data (the fact was public once it was
retired). The answer text is never stored: ``datasets/canaries/contamination_<date>.json`` holds the
counts and one yes/no per canary. The probe never gates anything. Only local providers are used
(``ollama``, ``openai_compatible_local``); with nothing retired (v1) no model is called.

Exit codes: 0 report written, 1 a call failed, 2 refused (model, lock, file).
"""

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path

from private_doc_plan import LOCAL_PROVIDERS

from pruefstand.attacks.rotation import RetiredCanary, load_retired
from pruefstand.core.config import LLMPolicyConfig, ModelRef
from pruefstand.core.errors import ConfigError, DatasetError, PruefstandError
from pruefstand.core.models.attacks import CanaryRegistry
from pruefstand.core.models.llm import LLMRequest, LLMRole
from pruefstand.llm.budget import Budget
from pruefstand.llm.client import LLMClient
from pruefstand.llm.factory import build_backend
from pruefstand.llm.policy import LLMPolicy
from pruefstand.llm.prompts import PromptRegistry
from pruefstand.llm.recorder import CallRecorder
from pruefstand.metrics.deterministic.normalise import contains_forbidden

REPO = Path(__file__).resolve().parents[1]
CANARY_DIR = REPO / "datasets" / "canaries"
PROMPTS = REPO / "packages" / "pruefstand" / "src" / "pruefstand" / "attacks" / "prompts"
PROMPT_ID = "generator.contamination.contamination_probe_de"
PROMPT_VERSION = "v1"
MAX_TOKENS = 200


def probeable(retired: Sequence[RetiredCanary]) -> list[RetiredCanary]:
    """Return the retired semantic canaries that can be asked (fact, question and pattern set)."""
    return [r for r in retired if r.fact and r.probe_question and r.forbidden_answer]


def known_by_model(answer: str, entry: RetiredCanary) -> bool:
    """Whether ``answer`` contains the canary's fact (its ``forbidden_answer`` pattern matches)."""
    return entry.forbidden_answer is not None and contains_forbidden(answer, entry.forbidden_answer)


def build_report(
    model: str, day: str, entries: Sequence[RetiredCanary], hits: Sequence[bool]
) -> dict[str, object]:
    """Assemble the report (no answer text).

    Args:
        model: The probed model id.
        day: ISO date of the run.
        entries: The canaries asked.
        hits: Per canary whether the model's answer matched.

    Returns:
        A JSON-serialisable mapping with counts and one yes/no per canary.
    """
    results = [
        {"token": e.token, "tenant": e.tenant, "retired_in": e.retired_in, "known": hit}
        for e, hit in zip(entries, hits, strict=True)
    ]
    return {
        "model": model, "date": day, "report_only": True, "n_probed": len(results),
        "n_known": sum(hits), "results": results,
    }  # fmt: skip


def make_client(ref: ModelRef, max_requests: int) -> LLMClient:
    """Build the client: local providers only, no cache."""
    policy = LLMPolicyConfig(allowed_providers=LOCAL_PROVIDERS)
    return LLMClient(
        build_backend(ref, policy=policy), None,
        Budget(max_usd=None, max_tokens=None, max_requests=max_requests),
        CallRecorder(), LLMPolicy(policy, CanaryRegistry(canaries=())),
    )  # fmt: skip


async def ask_all(ref: ModelRef, entries: Sequence[RetiredCanary]) -> list[bool]:
    """Ask every canary's question closed-book; return whether the answer knew the fact."""
    client = make_client(ref, len(entries))
    template = PromptRegistry(roots=[PROMPTS]).get(PROMPT_ID, PROMPT_VERSION)
    hits: list[bool] = []
    for entry in entries:
        request = LLMRequest(
            role=LLMRole.GENERATOR, model=ref.id,
            messages=template.render(question=entry.probe_question or ""),
            max_tokens=MAX_TOKENS, seed=0, prompt_id=PROMPT_ID, prompt_version=PROMPT_VERSION,
        )  # fmt: skip
        response = await client.complete(request)
        hits.append(known_by_model(response.text, entry))
    return hits


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    parser.add_argument("--model", required=True, help="the generator model id, e.g. ollama/<tag>")
    parser.add_argument("--family", required=True, help="family of --model")
    parser.add_argument("--retired", type=Path, default=CANARY_DIR / "retired.json")
    parser.add_argument("--out-dir", type=Path, default=CANARY_DIR)
    parser.add_argument("--date", default=None, help="YYYY-MM-DD (default: today)")
    return parser


def _check(args: argparse.Namespace, *, needs_model: bool) -> ModelRef:
    ref = ModelRef(id=args.model, family=args.family)
    provider = ref.id.split("/", 1)[0]
    if provider not in LOCAL_PROVIDERS:
        msg = (
            f"model {ref.id}: external provider '{provider}' refused; canaries stay on local models"
        )
        raise ConfigError(msg)
    if needs_model and os.environ.get("PRUEFSTAND_LOCK_HELD") != "1":
        msg = "run this script under 'pruefstand-lock' (the GPU lock, D212)"
        raise ConfigError(msg)
    if args.date is not None:
        date.fromisoformat(args.date)
    return ref


def main(argv: Sequence[str] | None = None) -> int:
    """Run the probe; returns the exit code (see the module docstring)."""
    args = _parser().parse_args(argv)
    try:
        entries = probeable(load_retired(args.retired))
        ref = _check(args, needs_model=bool(entries))
        hits = asyncio.run(ask_all(ref, entries)) if entries else []
        day = args.date or datetime.now(UTC).date().isoformat()
        report = build_report(ref.id, day, entries, hits)
        args.out_dir.mkdir(parents=True, exist_ok=True)
        target = args.out_dir / f"contamination_{day}.json"
        target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {target.name}: {report['n_known']} of {report['n_probed']} canaries known")
    except (ConfigError, DatasetError, ValueError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    except PruefstandError as exc:
        print(f"failed: {type(exc).__name__}: {str(exc)[:200]}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
