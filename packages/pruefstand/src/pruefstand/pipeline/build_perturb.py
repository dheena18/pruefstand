"""Stage ``perturb`` of ``build_dataset``: candidates -> cases -> perturbed variants (T4.7a).

Every kept candidate becomes a base ``TestCase`` (a candidate whose chunks would mix two share-alike
licence configs is dropped and counted as ``dropped_mixed_license``). Bases are ranked by
applicability, the number of perturbations that change the question (deterministic ones by running
them, LLM-assisted ones counted as applicable for German questions; W3.14). The deterministic
variants are made for every base, the LLM-assisted ones for the ``perturb.llm_bases`` top-ranked
public-tenant bases.
"""

from collections import Counter
from collections.abc import Mapping, Sequence

import numpy as np

from pruefstand.core.enums import Lang
from pruefstand.core.errors import ConfigError, DatasetError
from pruefstand.core.hashing import stable_hash
from pruefstand.core.ids import CaseId, ChunkId
from pruefstand.core.models.corpus import Chunk
from pruefstand.core.models.dataset import QACandidate
from pruefstand.core.models.testcase import TestCase
from pruefstand.dataset.generate_units import parse_prompt_version
from pruefstand.dataset.sampling import load_chunks
from pruefstand.dataset.to_case import to_test_case
from pruefstand.llm.client import LLMClient
from pruefstand.llm.recorder import CallRecorder
from pruefstand.perturb.batch import Item, RewriteStore, rewrite_pass, validate_pass
from pruefstand.perturb.llm_base import LLMRewritePerturbation
from pruefstand.perturb.llm_registry import build_llm_perturbation
from pruefstand.perturb.registry import get_perturbation, perturb_case, variant_case
from pruefstand.perturb.rewriter import PUBLIC_TENANT, LocalTarget, Rewriter
from pruefstand.perturb.validate import RewriteValidator
from pruefstand.pipeline.build_context import BuildContext, StageResult


def _by_id(case: TestCase) -> str:
    return case.id


def base_cases(
    cands: Sequence[QACandidate], chunks: Mapping[ChunkId, Chunk], corpus_version: str
) -> tuple[list[TestCase], int]:
    """Convert candidates to base cases; return them and the number dropped for mixed licences."""
    cases: dict[CaseId, TestCase] = {}
    mixed = 0
    for cand in cands:
        spec = parse_prompt_version(cand.prompt_version)
        extra = chunks.get(cand.extra_chunk_ids[0]) if cand.extra_chunk_ids else None
        try:
            case = to_test_case(
                cand, chunks[cand.chunk_id], spec.category, corpus_version=corpus_version,
                extra_chunk=extra,
            )  # fmt: skip
        except DatasetError:
            mixed += 1
            continue
        cases.setdefault(case.id, case)
    return sorted(cases.values(), key=lambda c: c.id), mixed


def deterministic_variants(base: TestCase, names: Sequence[str], seed: int) -> list[TestCase]:
    """Return the variants of ``base`` that the deterministic perturbations ``names`` change."""
    if base.lang is not Lang.DE:
        return []
    out: list[TestCase] = []
    for name in names:
        rng = np.random.default_rng(int(stable_hash("perturb", seed, base.id, name), 16))
        variant = perturb_case(base, get_perturbation(name), rng)
        if variant is not None:
            out.append(variant)
    return out


def applicability(base: TestCase, variants: Sequence[TestCase], n_llm: int) -> int:
    """The number of perturbations that apply to ``base`` (LLM-assisted ones count for German)."""
    return len(variants) + (n_llm if base.lang is Lang.DE else 0)


def _llm_perturbations(ctx: BuildContext) -> tuple[list[LLMRewritePerturbation], LLMClient]:
    models = ctx.cfg.models
    if models is None or models.rewriter is None or models.perturb_validator is None:
        msg = "perturb.llm needs models.rewriter and models.perturb_validator"
        raise ConfigError(msg)
    local = None
    if models.rewrite_local is not None:
        local = LocalTarget(ctx.clients.local(models.rewrite_local), models.rewrite_local.id)
    validator = RewriteValidator(
        ctx.clients.local(models.perturb_validator), models.perturb_validator.id,
        seed=ctx.cfg.perturb.seed,
    )  # fmt: skip
    rewriter = Rewriter(models.rewriter.id, local)
    client = ctx.clients.datagen(models.rewriter, ctx.cfg.generation.max_requests, CallRecorder())
    return [build_llm_perturbation(n, rewriter, validator) for n in ctx.cfg.perturb.llm], client


async def _llm_variants(ctx: BuildContext, bases: Sequence[TestCase]) -> list[TestCase]:
    perturbations, client = _llm_perturbations(ctx)
    items = [Item(id=b.id, text=b.question, private=b.tenant != PUBLIC_TENANT) for b in bases]
    store = RewriteStore(ctx.work.root / "perturb")
    seed = ctx.cfg.perturb.seed
    report = await rewrite_pass(items, perturbations, llm=client, store=store, seed=seed)
    if report.stopped or report.remaining:
        msg = f"perturb: the rewrite stopped ({report.stopped}); run the stage again"
        raise DatasetError(msg)
    by_id: dict[str, TestCase] = {b.id: b for b in bases}
    outcomes = await validate_pass(items, perturbations, store=store, seed=seed)
    return [
        variant_case(by_id[o.item_id], o.name, o.result.text) for o in outcomes if o.result.changed
    ]


async def perturb_stage(ctx: BuildContext) -> StageResult:
    """Run the ``perturb`` stage; return bases and variants (provisional split ``full``).

    Raises:
        ConfigError: ``perturb.llm`` without a rewriter and a validator model.
        DatasetError: A candidate's chunk is missing, or the rewrite was stopped (run again).
    """
    cfg = ctx.cfg.perturb
    chunks = {c.chunk_id: c for c in load_chunks(ctx.cfg.corpus_dir)}
    bases, mixed = base_cases(
        ctx.work.read("filter", QACandidate), chunks, ctx.manifest.corpus_version
    )
    variants = {b.id: deterministic_variants(b, cfg.deterministic, cfg.seed) for b in bases}
    ranked = sorted(
        (b for b in bases if b.lang is Lang.DE),
        key=lambda b: (-applicability(b, variants[b.id], len(cfg.llm)), b.id),
    )
    llm_bases = [b for b in ranked if b.tenant == PUBLIC_TENANT][: cfg.llm_bases] if cfg.llm else []
    llm_made = await _llm_variants(ctx, llm_bases) if llm_bases else []
    made = [v for vs in variants.values() for v in vs] + llm_made
    counters = {"bases": len(bases), "variants": len(made), "dropped_mixed_license": mixed}
    counters.update(
        {f"variant_{n}": c for n, c in sorted(Counter(v.perturbation for v in made).items()) if n}
    )
    counters["ranked_top_score"] = (
        applicability(ranked[0], variants[ranked[0].id], len(cfg.llm)) if ranked else 0
    )
    every = sorted([*bases, *made], key=_by_id)
    return every, counters
