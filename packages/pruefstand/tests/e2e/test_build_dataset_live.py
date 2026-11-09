"""The whole ``build-dataset`` pipeline on the real tier-1 stack (T4.7a S5, [DOCKER] [NET]).

Needs the `live` stack (``make up PROFILES="core live dev" WAIT=1``: TEI embeddings, the CPU
llama.cpp model) and ``PRUEFSTAND_GH_MODELS_TOKEN`` (GitHub Models, Models: read) for the datagen
model. The slice corpus is real; the datagen, support and embedding calls are real. Run:
``uv run pytest -m "e2e and live" packages/pruefstand/tests/e2e/test_build_dataset_live.py -q``.
"""

import asyncio
import os
from collections import defaultdict
from pathlib import Path

import pytest
from testsupport.qa_support import REPO

from pruefstand.core.config import DatasetBuildConfig
from pruefstand.core.config_loader import load_model
from pruefstand.core.enums import Category, Split
from pruefstand.dataset.io import read_dataset
from pruefstand.dataset.validate import validate_dataset
from pruefstand.pipeline.build_dataset import BuildResult, run_build
from pruefstand.pipeline.build_state import STAGES, Workdir

CONFIG = REPO / "packages/pruefstand/tests/fixtures/dataset_small.yaml"
EXCLUDE = REPO / "experiments/model_selection/indomain_dev_sources.json"
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.live,
    pytest.mark.network,
    pytest.mark.skipif(
        not (
            os.environ.get("PRUEFSTAND_GH_MODELS_TOKEN") and os.environ.get("PRUEFSTAND_EMBED_URL")
        ),
        reason="needs PRUEFSTAND_GH_MODELS_TOKEN and PRUEFSTAND_EMBED_URL (the live stack)",
    ),
]


@pytest.fixture(scope="module")
def build(tmp_path_factory: pytest.TempPathFactory) -> tuple[DatasetBuildConfig, BuildResult]:
    """Build the small dataset once with the real models; work and output go to a temp dir."""
    tmp = tmp_path_factory.mktemp("slice-build")
    loaded = load_model(CONFIG, DatasetBuildConfig)
    cfg = loaded.model_copy(
        update={
            "corpus_dir": REPO / "corpus/slice_v1",
            "out_dir": tmp / "datasets" / "fixtures",
            "work_dir": tmp / "work",
            "generation": loaded.generation.model_copy(update={"exclude_file": EXCLUDE}),
        }
    )
    port = os.environ.get("LLM_HOST_PORT", "8080")
    os.environ.setdefault("PRUEFSTAND_JUDGE_BASE_URL", f"http://127.0.0.1:{port}/v1")
    return cfg, asyncio.run(run_build(cfg, root=REPO))


def test_the_built_dataset_validates_and_matches_the_plan(
    build: tuple[DatasetBuildConfig, BuildResult],
) -> None:
    cfg, result = build
    assert validate_dataset(result.directory) == []
    manifest = result.manifest
    assert manifest is not None
    assert manifest.splits[Split.SMOKE] == cfg.split_plan.smoke_size
    assert manifest.prompt_versions["qa_factual_de"] == "v1"
    assert result.report["dropped_mixed_license"] in range(1000)


def test_every_cluster_is_in_one_split_and_attack_cases_are_present(
    build: tuple[DatasetBuildConfig, BuildResult],
) -> None:
    _, result = build
    loaded = read_dataset(result.directory)
    where: dict[str, set[Split]] = defaultdict(set)
    categories = set()
    for split, cases in loaded.cases.items():
        for case in cases:
            where[case.cluster_id].add(split)
            categories.add(case.category)
    assert all(len(s - {Split.ROBUST_PR, Split.RQ1}) <= 1 for s in where.values())
    assert Category.UNANSWERABLE in categories
    probes = {Category.LEAK_PROBE, Category.FILTER_BYPASS, Category.SYSTEM_PROMPT_EXTRACTION}
    assert categories & probes


def test_robust_pr_has_bases_with_perturbed_variants(
    build: tuple[DatasetBuildConfig, BuildResult],
) -> None:
    _, result = build
    cases = read_dataset(result.directory).cases[Split.ROBUST_PR]
    bases = {c.id for c in cases if c.perturbation is None}
    assert len(bases) == 2
    assert any(c.perturbation for c in cases)
    assert all(c.base_id in bases for c in cases if c.perturbation)


def test_resume_after_deleting_the_last_stage_reruns_only_that_stage(
    build: tuple[DatasetBuildConfig, BuildResult],
) -> None:
    cfg, _ = build
    work = Workdir(cfg.work_dir / f"{cfg.name}-{cfg.dataset_version}")
    before = {n: work.path(n).stat().st_mtime_ns for n in STAGES[:-1]}
    work.path("validate").unlink(missing_ok=True)
    work.path("validate").with_suffix(".meta.json").unlink(missing_ok=True)
    asyncio.run(run_build(cfg, resume=True, root=REPO))
    assert {n: work.path(n).stat().st_mtime_ns for n in STAGES[:-1]} == before
    assert Path(cfg.out_dir).exists()
