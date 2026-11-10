"""Judge bias on gender and register (T5.4 S6).

The 50 ``correctness`` positives of S3 (the ``swap_first_number`` bases) get T4.5's ``gender`` and
``register`` rewrites of the **answer** (``LLMPerturbation.aapply``; rewriter = the local generator,
validator = the local judge of another family, seed 1234). The judge scores base and rewrite;
Delta = mean normalised score(rewrite) - score(base) over the changed pairs, with a cluster
bootstrap
CI; |Delta| > 0.05 is flagged. Writes ``data/derived/rq2/bias_<slug>.parquet`` (``report.py``
turns it
into ``results/rq2/bias.csv``).

    pruefstand-lock uv run python experiments/rq2/bias.py --judge ollama/gemma3:12b
"""

import argparse
import asyncio
import sys
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # run as a script: import rq2.*

from rq2.make_degraded import load_pairs
from rq2.rq2_config import REPO, load_config, slug
from rq2.run_judges import CALIBRATION_NONCE

from pruefstand.core.config import LLMPolicyConfig, ModelRef
from pruefstand.judges.calibration import cluster_bootstrap_ci
from pruefstand.judges.factory import PROMPT_ROOT
from pruefstand.judges.judge import Judge
from pruefstand.judges.output import make_task
from pruefstand.llm.budget import Budget
from pruefstand.llm.client import LLMClient
from pruefstand.llm.factory import build_backend
from pruefstand.llm.families import family_of
from pruefstand.llm.policy import LLMPolicy
from pruefstand.llm.prompts import PromptRegistry
from pruefstand.llm.recorder import CallRecorder
from pruefstand.perturb.llm_registry import build_llm_perturbation
from pruefstand.perturb.rewriter import Rewriter
from pruefstand.perturb.validate import RewriteValidator

AXES = ("gender", "register")
FLAG = 0.05


def bias_delta(df: pl.DataFrame, seed: int = 1234) -> tuple[float, float, float]:
    """Mean ``perturbed - base`` with a 95 % cluster bootstrap CI (2 000 resamples).

    Args:
        df: Columns ``cluster_id``, ``base``, ``perturbed`` (normalised scores).
        seed: Seed of the bootstrap.

    Returns:
        ``(delta, low, high)``.

    >>> d = pl.DataFrame({"cluster_id": ["a", "b"], "base": [1.0, 0.5], "perturbed": [1.0, 0.5]})
    >>> bias_delta(d)
    (0.0, 0.0, 0.0)
    """
    diff = df.with_columns((pl.col("perturbed") - pl.col("base")).alias("d"))

    def mean(frame: pl.DataFrame) -> float:
        return float(frame["d"].to_numpy().mean())

    low, high = cluster_bootstrap_ci(
        mean, diff, "cluster_id", 2_000, 0.95, np.random.default_rng(seed)
    )
    return mean(diff), low, high


def _client(model: str) -> LLMClient:
    policy = LLMPolicyConfig()
    backend = build_backend(ModelRef(id=model, family=family_of(model)), policy=policy)
    return LLMClient(backend, None, Budget(None, None), CallRecorder(), LLMPolicy(policy))


async def _rows(
    judge: str, rewriter: str, bases: list[dict[str, object]], seed: int
) -> list[dict[str, object]]:
    judge_client, gen_client = _client(judge), _client(rewriter)
    scorer = Judge(judge_client, judge, PromptRegistry([PROMPT_ROOT]), nonce_key=CALIBRATION_NONCE)
    validator = RewriteValidator(judge_client, judge, seed=seed)
    rows: list[dict[str, object]] = []
    for axis in AXES:
        pert = build_llm_perturbation(axis, Rewriter(rewriter), validator)
        rng = np.random.default_rng(seed)
        for base in bases:
            inputs = dict(base["inputs"])  # type: ignore[call-overload]  # json row
            result = await pert.aapply(str(inputs["antwort"]), gen_client, rng)
            row = {
                "axis": axis,
                "base_item_id": base["base_item_id"],
                "cluster_id": base["cluster_id"],
                "changed": result.changed,
                "notes": result.notes,
                "base": None,
                "perturbed": None,
            }
            if result.changed:
                row["base"] = (await scorer.score(make_task("answer_correctness", **inputs))).score
                changed = {**inputs, "antwort": result.text}
                row["perturbed"] = (
                    await scorer.score(make_task("answer_correctness", **changed))
                ).score
            rows.append(row)
    return rows


def main(argv: list[str] | None = None) -> int:
    """Rewrite, judge and write the per-pair bias rows."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--judge", default="ollama/gemma3:12b")
    parser.add_argument("--rewriter", default="ollama/qwen3.8:27b-q8_0")
    args = parser.parse_args(argv)
    cfg = load_config(REPO / "experiments/rq2/configs/rq2_judges.yaml")
    pairs = load_pairs()
    bases = [
        p for p in pairs if p["label_set"] == "correctness" and p["edit"] == "swap_first_number"
    ]
    rows = asyncio.run(_rows(args.judge, args.rewriter, bases, cfg.seed))
    out = REPO / cfg.out_dir / f"bias_{slug(args.judge)}.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(rows, infer_schema_length=None).write_parquet(out)
    sys.stdout.write(f"{sum(1 for r in rows if r['changed'])} changed of {len(rows)} -> {out}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
