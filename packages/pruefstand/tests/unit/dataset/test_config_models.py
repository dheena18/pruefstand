"""``SplitPlan`` and ``DatasetBuildConfig`` (T4.1 S1)."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from pruefstand.core.config import DatasetBuildConfig, SplitPlan


def test_defaults_equal_the_plan_table() -> None:
    plan = SplitPlan()
    assert (plan.smoke_size, plan.smoke_min_per_category) == (50, 3)
    assert (plan.core_answerable, plan.core_unanswerable, plan.core_injection) == (220, 50, 30)
    assert plan.core_min_cross_lingual == 30
    assert plan.core_min_answerable_clusters == 200
    assert plan.judged_subset_size == 150
    assert (plan.robust_pr_bases, plan.robust_pr_min_perturbed) == (40, 300)
    assert (plan.full_refusal, plan.full_block_unperturbed, plan.full_block_perturbed) == (
        150,
        300,
        150,
    )
    assert plan.full_block_min_clusters == 250
    assert plan.rq1_bases == 300
    assert plan.nightly_cap == 600
    assert len(plan.robust_pr_types) == 11


def test_robust_pr_min_bases_per_type_defaults_to_twenty() -> None:
    assert SplitPlan().robust_pr_min_bases_per_type == 20


def test_negative_size_is_an_error() -> None:
    with pytest.raises(ValidationError):
        SplitPlan(core_answerable=-1)


def test_subset_larger_than_core_is_an_error() -> None:
    with pytest.raises(ValidationError, match="judged_subset_size"):
        SplitPlan(judged_subset_size=301)


def test_refusal_bounds_must_enclose_the_size() -> None:
    with pytest.raises(ValidationError, match="full_refusal"):
        SplitPlan(full_refusal=100)


def test_extra_field_is_an_error() -> None:
    with pytest.raises(ValidationError):
        DatasetBuildConfig.model_validate(
            {"name": "x", "dataset_version": "v1", "corpus_dir": "c", "surprise": 1}
        )


def test_json_round_trip() -> None:
    cfg = DatasetBuildConfig(
        name="pruefstand-de",
        dataset_version="v1",
        corpus_dir=Path("corpus/c1"),
        seed=7,
        prompt_versions={"qa": "qa_de_v1"},
    )
    assert DatasetBuildConfig.model_validate_json(cfg.model_dump_json()) == cfg
    assert cfg.split_plan == SplitPlan()
