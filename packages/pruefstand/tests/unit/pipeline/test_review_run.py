"""Spot-check sample, summary and ``apply`` on a built slice dataset (T4.7a)."""

import asyncio
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest
from testsupport.build_support import SLICE_DIR, offline_clients, small_plan, write_candidates
from testsupport.review_support import REVIEWER

from pruefstand.core.config import (
    BuildModels,
    DatasetBuildConfig,
    EmbedConfig,
    GenerationConfig,
    ModelRef,
    ReviewConfig,
    ReviewersConfig,
)
from pruefstand.core.errors import ConfigError, DatasetError
from pruefstand.core.models.dataset import ReviewItem, SpotDecision
from pruefstand.core.models.testcase import TestCase
from pruefstand.dataset.io import read_dataset
from pruefstand.dataset.validate import validate_dataset
from pruefstand.pipeline.build_dataset import run_build
from pruefstand.pipeline.review_run import (
    ITEMS,
    SPOT_DECISIONS,
    apply_review,
    dataset_dir,
    read_items,
    review_dir,
    summarise,
    write_spotcheck_sample,
)

GEMMA = ModelRef(id=REVIEWER, family="gemma")
TODAY = datetime(2026, 11, 9, 9, 0, tzinfo=UTC)


def _cfg(tmp_path: Path, *, review: bool = True) -> DatasetBuildConfig:
    return DatasetBuildConfig(
        name="pruefstand-de-small",
        dataset_version="v1",
        corpus_dir=SLICE_DIR,
        out_dir=tmp_path / "datasets" / "fixtures",
        work_dir=tmp_path / "work",
        split_plan=small_plan(),
        seed=5,
        generation=GenerationConfig(candidates_from=write_candidates(tmp_path / "c.jsonl")),
        embed=EmbedConfig(url="http://embed.invalid"),
        check_refusal_laws=False,
        models=BuildModels(
            datagen=ModelRef(id="github/openai/gpt-4.1-mini", family="gpt"),
            generator=ModelRef(id="ollama/qwen3.8:27b-q8_0", family="qwen"),
        ),
        review=ReviewConfig(reviewers=ReviewersConfig(core_smoke=GEMMA, full=GEMMA))
        if review
        else None,
    )


@pytest.fixture
def built(tmp_path: Path) -> DatasetBuildConfig:
    cfg = _cfg(tmp_path)
    asyncio.run(run_build(cfg, clients=offline_clients()))
    return cfg


def _item(
    case_id: str, cluster: str, category: str, version: str, verdict: str, **extra: str
) -> ReviewItem:
    return ReviewItem.model_validate(
        {
            "case_id": case_id, "cluster_id": cluster, "category": category,
            "prompt_version": version, "split": "core", "verdict": verdict,
            "reason": "Begründung.", "model": REVIEWER, **extra,
        }
    )  # fmt: skip


def _write_items(cfg: DatasetBuildConfig, rejects: int, fixes: int) -> list[ReviewItem]:
    cases = [c for v in read_dataset(dataset_dir(cfg)).cases.values() for c in v]
    answerable = [c for c in cases if c.perturbation is None and c.generation_prompt_version]
    items: list[ReviewItem] = []
    for n, case in enumerate(answerable):
        verdict = "reject" if n < rejects else "fix" if n < rejects + fixes else "ok"
        extra = (
            {"fixed_question": "Wie lang ist die Frist, wenn ich neu anfange?"}
            if verdict == "fix"
            else {}
        )
        items.append(
            _item(
                case.id,
                case.cluster_id,
                case.category.value,
                case.generation_prompt_version or "none",
                verdict,
                **extra,
            )
        )
    review_dir(cfg).mkdir(parents=True, exist_ok=True)
    (review_dir(cfg) / ITEMS).write_text(
        "".join(i.model_dump_json() + "\n" for i in items), "utf-8"
    )
    return items


def test_apply_removes_rejected_clusters_fixes_questions_and_records_rounds(
    built: DatasetBuildConfig,
) -> None:
    before = [c for v in read_dataset(dataset_dir(built)).cases.values() for c in v]
    items = _write_items(built, rejects=1, fixes=1)
    report = apply_review(built, today=TODAY)
    loaded = read_dataset(dataset_dir(built))
    after: dict[str, TestCase] = {c.id: c for v in loaded.cases.values() for c in v}
    rejected, fixed = items[0], items[1]
    assert rejected.cluster_id not in {c.cluster_id for c in after.values()}
    assert report.rejected >= 1
    if fixed.case_id in after:  # its cluster may share the rejected one's document
        assert after[fixed.case_id].question == fixed.fixed_question
        assert after[fixed.case_id].source == "generated+model-reviewed"
    assert len(after) == len(before) - report.rejected - report.variants_dropped
    assert loaded.manifest is not None
    (round_,) = [r for r in loaded.manifest.review if r.reviewer.startswith("model:")]
    assert round_.reviewer == f"model:{REVIEWER}@review_item_de_v1"
    assert round_.prompt_version == "qa_factual_de_v1"
    assert round_.sampled == len(items)
    assert round_.bad == 2
    assert validate_dataset(dataset_dir(built)) == []


def test_apply_adds_one_owner_round_per_spot_checker(built: DatasetBuildConfig) -> None:
    items = _write_items(built, rejects=0, fixes=0)
    decisions = [
        SpotDecision(
            case_id=i.case_id, citation_ok=n != 0, plausible=True,
            reviewer="owner-spotcheck:anna", ts=TODAY,
        )
        for n, i in enumerate(items[:4])
    ]  # fmt: skip
    (review_dir(built) / SPOT_DECISIONS).write_text(
        "".join(d.model_dump_json() + "\n" for d in decisions), "utf-8"
    )
    apply_review(built, today=TODAY)
    manifest = read_dataset(dataset_dir(built)).manifest
    assert manifest is not None
    (owner,) = [r for r in manifest.review if r.reviewer.startswith("owner-spotcheck:")]
    assert (owner.reviewer, owner.sampled, owner.bad) == ("owner-spotcheck:anna", 4, 1)
    assert owner.round == len(manifest.review)


def test_summary_reports_rates_flags_and_the_trust_verdict(built: DatasetBuildConfig) -> None:
    items = _write_items(built, rejects=0, fixes=0)
    assert summarise(built).trusted is None  # no decisions yet
    decisions = [
        SpotDecision(case_id=i.case_id, citation_ok=False, plausible=True,
                     reviewer="owner-spotcheck:anna", ts=TODAY)
        for i in items[:2]
    ]  # fmt: skip
    (review_dir(built) / SPOT_DECISIONS).write_text(
        "".join(d.model_dump_json() + "\n" for d in decisions), "utf-8"
    )
    summary = summarise(built)
    assert (summary.ok_checked, summary.ok_flagged) == (2, 2)
    assert summary.trusted is False
    assert summary.rates["factual/qa_factual_de_v1"].error_rate == 0.0


def test_the_spotcheck_sample_covers_the_smoke_split(built: DatasetBuildConfig) -> None:
    _write_items(built, rejects=0, fixes=0)
    picked = write_spotcheck_sample(built)
    smoke = read_dataset(dataset_dir(built)).cases["smoke"]  # type: ignore[index]
    assert {c.id for c in smoke} <= {c.id for c in picked}
    assert (review_dir(built) / "spotcheck_sample.jsonl").is_file()


def test_apply_needs_items_and_a_review_block(built: DatasetBuildConfig, tmp_path: Path) -> None:
    with pytest.raises(DatasetError, match="no review items"):
        apply_review(built, today=TODAY)
    (tmp_path / "x").mkdir()
    with pytest.raises(ConfigError, match="review"):
        summarise(_cfg(tmp_path / "x", review=False))
    assert read_items(built) == []


def test_a_second_apply_of_the_same_review_is_refused(built: DatasetBuildConfig) -> None:
    _write_items(built, rejects=1, fixes=0)
    apply_review(built, today=TODAY)
    manifest = read_dataset(dataset_dir(built)).manifest
    assert manifest is not None
    with pytest.raises(DatasetError, match="already applied"):
        apply_review(built, today=TODAY)
    again = read_dataset(dataset_dir(built)).manifest
    assert again is not None
    assert len(again.review) == len(manifest.review)  # no round was appended twice


def test_apply_on_a_real_directory_keeps_the_dataset_when_a_quota_breaks(
    built: DatasetBuildConfig, tmp_path: Path
) -> None:
    """Below ``datasets/fixtures`` quota findings are warnings; on a real build they are problems.

    A reject lowers the counts under the SPEC quotas, so ``apply`` fails and keeps the dataset. The
    intended flow on a real build is reject, regenerate (``--only``), rebuild, review again, apply
    (D753).
    """
    real_out = tmp_path / "release"
    shutil.copytree(built.out_dir / built.name, real_out / built.name)
    real = built.model_copy(update={"out_dir": real_out})
    before = {p.name: p.read_bytes() for p in dataset_dir(real).iterdir()}
    _write_items(real, rejects=1, fixes=0)
    with pytest.raises(DatasetError, match="old dataset is kept"):
        apply_review(real, today=TODAY)
    assert {p.name: p.read_bytes() for p in dataset_dir(real).iterdir()} == before
    assert not dataset_dir(real).with_name("v1.new").exists()
