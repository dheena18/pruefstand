"""Model review, owner spot-check sample and ``apply`` of a built dataset (T4.7a).

All review artefacts live in ``<work_dir>/<name>-<version>/review/`` (git-ignored):
``sample.jsonl`` (ids of the reviewed cases), ``items.jsonl`` (one ``ReviewItem`` per reviewed
case, written as they arrive, the resume record), ``spotcheck_sample.jsonl`` (ids for the owner)
and ``spotcheck_decisions.jsonl`` (written by the review app). Only ``apply_review`` writes into
``<out_dir>/<name>/<version>/``.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TextIO

from pruefstand.core.config import DatasetBuildConfig, ModelRef, ReviewConfig
from pruefstand.core.models.dataset import ReviewItem
from pruefstand.core.models.testcase import TestCase
from pruefstand.dataset.model_review import check_reviewer, review_with_model
from pruefstand.dataset.review import (
    StratumRate,
    error_rates,
    sample_for_review,
    sample_spotcheck,
    spotcheck_trust,
)
from pruefstand.dataset.sampling import load_chunks
from pruefstand.pipeline.build_clients import BuildClients
from pruefstand.pipeline.review_apply import ApplyReport, apply_review
from pruefstand.pipeline.review_files import (
    APPLIED,
    ITEMS,
    SAMPLE,
    SPOT_DECISIONS,
    SPOT_SAMPLE,
    SPOTCHECK_VERSION,
    dataset_dir,
    read_cases,
    read_decisions,
    read_items,
    require_review,
    review_dir,
)

__all__ = [
    "APPLIED",
    "ITEMS",
    "SAMPLE",
    "SPOTCHECK_VERSION",
    "SPOT_DECISIONS",
    "SPOT_SAMPLE",
    "ApplyReport",
    "ModelReviewRun",
    "Summary",
    "apply_review",
    "dataset_dir",
    "read_decisions",
    "read_items",
    "review_dir",
    "run_model_review",
    "summarise",
    "write_spotcheck_sample",
]


@dataclass(frozen=True)
class ModelReviewRun:
    """Result of ``run_model_review``: counts and the error rate per stratum."""

    reviewed: int
    failed: tuple[str, ...]
    rates: dict[str, StratumRate]


async def run_model_review(
    cfg: DatasetBuildConfig, clients: BuildClients, *, concurrency: int = 4
) -> ModelReviewRun:
    """Review the sample of the built dataset with the configured reviewers.

    The sample is 100 % of ``smoke`` and ``core`` and attack/probe cases, a seeded part of the
    rest. Items already in ``items.jsonl`` are reused, so an interrupted run continues.

    Raises:
        ConfigError: No ``review`` block, or a reviewer breaks the family rule.
        DatasetError: The dataset cannot be read.
    """
    review = require_review(cfg)
    assert cfg.models is not None  # noqa: S101  (require_review checked it; narrows the type)
    cases, _ = read_cases(cfg)
    chosen = sample_for_review(
        cases, seed=cfg.seed, full_fraction=review.full_fraction,
        min_per_category=review.min_per_category,
    )  # fmt: skip
    out = review_dir(cfg)
    out.mkdir(parents=True, exist_ok=True)
    (out / SAMPLE).write_text("".join(json.dumps({"id": c.id}) + "\n" for c in chosen), "utf-8")
    sources = load_chunks(cfg.corpus_dir)
    done = {i.case_id: i for i in read_items(cfg)}
    failed: list[str] = []
    for ref, group in _groups(review, chosen):
        check_reviewer(ref, generator=cfg.models.generator, datagen=cfg.models.datagen)
        with (out / ITEMS).open("a", encoding="utf-8", newline="\n") as handle:

            def write(item: ReviewItem, handle: TextIO = handle) -> None:
                handle.write(item.model_dump_json() + "\n")

            outcome = await review_with_model(
                group, sources, clients.local(ref), ref.id, concurrency=concurrency,
                sink=write, skip=done,
            )  # fmt: skip
        failed += outcome.failed
    items = read_items(cfg)
    return ModelReviewRun(
        len(items), tuple(failed), error_rates(items, threshold=review.error_threshold)
    )


def _groups(
    review: ReviewConfig, chosen: Sequence[TestCase]
) -> list[tuple[ModelRef, list[TestCase]]]:
    core = [c for c in chosen if c.split.value in {"smoke", "core"}]
    rest = [c for c in chosen if c.split.value not in {"smoke", "core"}]
    groups = [(review.reviewers.core_smoke, core), (review.reviewers.full, rest)]
    return [(ref, g) for ref, g in groups if g]


def write_spotcheck_sample(cfg: DatasetBuildConfig) -> list[TestCase]:
    """Draw the owner spot-check sample (all smoke plus a stratified draw) and write its ids."""
    review = require_review(cfg)
    cases, _ = read_cases(cfg)
    picked = sample_spotcheck(cases, read_items(cfg), seed=cfg.seed, size=review.spotcheck_size)
    out = review_dir(cfg)
    out.mkdir(parents=True, exist_ok=True)
    (out / SPOT_SAMPLE).write_text(
        "".join(json.dumps({"id": c.id}) + "\n" for c in picked), "utf-8"
    )
    return picked


@dataclass(frozen=True)
class Summary:
    """Model error rates per stratum, the owner's flag rates and the trust verdict."""

    rates: dict[str, StratumRate]
    spot_checked: int
    spot_flagged: int
    ok_checked: int
    ok_flagged: int
    trusted: bool | None


def summarise(cfg: DatasetBuildConfig) -> Summary:
    """Summarise the review: rates, spot-check counts and trust (None = no decisions yet)."""
    review = require_review(cfg)
    items = read_items(cfg)
    decisions = read_decisions(cfg)
    ok = {i.case_id for i in items if i.verdict == "ok"}
    flagged = [d for d in decisions if not (d.citation_ok and d.plausible)]
    return Summary(
        rates=error_rates(items, threshold=review.error_threshold),
        spot_checked=len(decisions),
        spot_flagged=len(flagged),
        ok_checked=sum(1 for d in decisions if d.case_id in ok),
        ok_flagged=sum(1 for d in flagged if d.case_id in ok),
        trusted=spotcheck_trust(decisions, items, max_flag_rate=review.spotcheck_max_flag_rate)
        if decisions
        else None,
    )
