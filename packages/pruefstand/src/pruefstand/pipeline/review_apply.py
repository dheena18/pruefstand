"""``apply``: write the model review and the owner spot-check into the dataset (T4.7a)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from pruefstand.core.config import DatasetBuildConfig
from pruefstand.core.errors import DatasetError
from pruefstand.core.models.dataset import ReviewRound, SpotDecision
from pruefstand.dataset.io import build_manifest
from pruefstand.dataset.review import apply_decisions
from pruefstand.pipeline.build_state import file_digest, input_hash
from pruefstand.pipeline.review_files import (
    APPLIED,
    ITEMS,
    SPOT_DECISIONS,
    SPOTCHECK_VERSION,
    dataset_dir,
    read_cases,
    read_decisions,
    read_items,
    replace_dataset,
    require_review,
    review_dir,
)


def _owner_rounds(decisions: Sequence[SpotDecision], first: int) -> list[ReviewRound]:
    by_reviewer: dict[str, list[SpotDecision]] = {}
    for d in decisions:
        by_reviewer.setdefault(d.reviewer, []).append(d)
    rounds: list[ReviewRound] = []
    for offset, name in enumerate(sorted(by_reviewer)):
        group = by_reviewer[name]
        bad = sum(1 for d in group if not (d.citation_ok and d.plausible))
        rounds.append(
            ReviewRound(
                round=first + offset, prompt_version=SPOTCHECK_VERSION, sampled=len(group),
                bad=bad, error_rate=bad / len(group), reviewer=name,
                date=max(d.ts for d in group).date(),
            )
        )  # fmt: skip
    return rounds


def _state(cfg: DatasetBuildConfig) -> str:
    """Digest of the review input and of the dataset manifest as it is now."""
    return input_hash(
        "applied",
        cfg.name,
        file_digest(review_dir(cfg) / ITEMS),
        file_digest(review_dir(cfg) / SPOT_DECISIONS),
        file_digest(dataset_dir(cfg) / "dataset_manifest.json"),
    )


def _refuse_second_apply(cfg: DatasetBuildConfig) -> None:
    marker = review_dir(cfg) / APPLIED
    if marker.is_file() and marker.read_text("utf-8").strip() == _state(cfg):
        msg = (
            "these review results are already applied to this dataset; build or review again first"
        )
        raise DatasetError(msg)


def _mark_applied(cfg: DatasetBuildConfig) -> None:
    """Remember the state after ``apply`` so a second call cannot append the rounds twice."""
    (review_dir(cfg) / APPLIED).write_text(_state(cfg) + "\n", encoding="utf-8")


@dataclass(frozen=True)
class ApplyReport:
    """What ``apply_review`` changed."""

    rejected: int
    fixed: int
    variants_dropped: int
    rounds: int
    needs_regeneration: tuple[str, ...]
    cases: int


def apply_review(cfg: DatasetBuildConfig, *, today: datetime | None = None) -> ApplyReport:
    """Apply the model review and the owner spot-check to the dataset directory.

    Rejects remove the case and its cluster from every split, fixes replace the question,
    ``ReviewRound`` entries are appended to the manifest (model rounds per generation prompt, one
    owner round per spot-checker), and the dataset is validated afterwards.

    Raises:
        ConfigError: No ``review`` block.
        DatasetError: There are no review items yet, or the result does not validate.
    """
    review = require_review(cfg)
    assert cfg.models is not None  # noqa: S101  (narrows the type; require_review checked it)
    items = read_items(cfg)
    if not items:
        msg = "no review items; run the model review first (make review-model)"
        raise DatasetError(msg)
    _refuse_second_apply(cfg)
    cases, manifest = read_cases(cfg)
    model_id = next((i.model for i in items if i.model != "deterministic"), "none")
    stamp = (today or datetime.now(UTC)).date()
    result = apply_decisions(
        cases, items, reviewer=f"model:{model_id}@{review.prompt_version}", today=stamp,
        existing=manifest.review, threshold=review.error_threshold,
    )  # fmt: skip
    rounds = [*manifest.review, *result.rounds]
    rounds += _owner_rounds(read_decisions(cfg), len(rounds) + 1)
    updated = build_manifest(
        manifest.name, manifest.version, manifest.corpus_version, result.cases,
        seed=manifest.assignment_seed, prompt_versions=manifest.prompt_versions,
        review=tuple(rounds), created_at=manifest.created_at,
    )  # fmt: skip
    directory = dataset_dir(cfg)
    replace_dataset(directory, result.cases, updated)
    _mark_applied(cfg)
    return ApplyReport(
        len(result.rejected), len(result.fixed), len(result.variants_dropped), len(rounds),
        result.needs_regeneration, len(result.cases),
    )  # fmt: skip
