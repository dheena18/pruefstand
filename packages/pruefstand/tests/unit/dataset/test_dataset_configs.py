"""The committed ``dataset.yaml`` and ``dataset_small.yaml`` are valid and follow the rules."""

import pytest
from testsupport.qa_support import REPO

from pruefstand.core.config import DatasetBuildConfig, SplitPlan
from pruefstand.core.config_loader import load_model

FILES = (REPO / "dataset.yaml", REPO / "packages/pruefstand/tests/fixtures/dataset_small.yaml")


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_the_config_loads_and_keeps_the_family_separation(path) -> None:  # type: ignore[no-untyped-def]
    cfg = load_model(path, DatasetBuildConfig)
    assert cfg.models is not None
    assert cfg.models.datagen.family not in {"qwen", "gemma"}
    assert cfg.review is not None
    for ref in (cfg.review.reviewers.core_smoke, cfg.review.reviewers.full):
        assert ref.family not in {cfg.models.datagen.family, cfg.models.generator.family}
    assert (cfg.corpus_dir / "manifest.json").parent.name.startswith("slice")


def test_the_release_config_uses_the_spec_split_plan_and_the_local_judge() -> None:
    cfg = load_model(FILES[0], DatasetBuildConfig)
    assert cfg.split_plan == SplitPlan()
    assert cfg.models is not None
    assert cfg.models.support is not None
    assert cfg.models.support.id.startswith("ollama/")
    assert cfg.review is not None
    assert cfg.review.reviewers.core_smoke.id == cfg.models.support.id  # the one judge (D330)


def test_the_small_config_builds_a_fixture_path() -> None:
    cfg = load_model(FILES[1], DatasetBuildConfig)
    assert "fixtures" in cfg.out_dir.parts  # quota findings are warnings below datasets/fixtures
    assert cfg.split_plan.core_size < 20
