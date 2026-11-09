"""``build_dataset`` stage by stage on the real slice corpus, without a model (T4.7a).

The candidates are hand-written for real chunks (``testsupport.build_support``) and the embedding is
a trigram function: this test covers the orchestration (stage files, resume, ranking, licence drops,
splits, validation). The generation, support, rewrite and review models run in the live test
(``tests/e2e/test_build_dataset_live.py``); that is why the row in the test matrix stays ``weak``.
"""

import asyncio
from pathlib import Path

import pytest
from testsupport.build_support import (
    SLICE_DIR,
    candidate,
    candidates,
    offline_clients,
    small_plan,
    write_candidates,
)
from testsupport.qa_support import as_chunk, client_factory, datagen_server, slice_chunks

from pruefstand.core.config import (
    BuildModels,
    DatasetBuildConfig,
    EmbedConfig,
    GenerationConfig,
    ModelRef,
    PerturbConfig,
)
from pruefstand.core.enums import Category, Split
from pruefstand.core.errors import ConfigError
from pruefstand.core.models.dataset import QACandidate
from pruefstand.core.models.testcase import TestCase
from pruefstand.dataset.io import read_dataset
from pruefstand.dataset.validate import validate_dataset
from pruefstand.pipeline.build_clients import BuildClients
from pruefstand.pipeline.build_dataset import build_dataset, run_build
from pruefstand.pipeline.build_perturb import base_cases
from pruefstand.pipeline.build_state import STAGES, Workdir


def _config(tmp_path: Path, **changes: object) -> DatasetBuildConfig:
    fields: dict[str, object] = {
        "name": "pruefstand-de-small",
        "dataset_version": "v1",
        "corpus_dir": SLICE_DIR,
        "out_dir": tmp_path / "datasets" / "fixtures",  # quota findings are warnings there
        "work_dir": tmp_path / "work",
        "split_plan": small_plan(),
        "seed": 5,
        "generation": GenerationConfig(candidates_from=write_candidates(tmp_path / "c.jsonl")),
        "embed": EmbedConfig(url="http://embed.invalid"),
        "perturb": PerturbConfig(),
        "check_refusal_laws": False,  # the slice has three laws; the templates name more
    }
    return DatasetBuildConfig.model_validate({**fields, **changes})


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory):  # type: ignore[no-untyped-def]
    tmp = tmp_path_factory.mktemp("build")
    cfg = _config(tmp)
    result = pytest.importorskip("asyncio").run(run_build(cfg, clients=offline_clients()))
    return cfg, result


def test_the_build_writes_a_valid_dataset(built) -> None:  # type: ignore[no-untyped-def]
    _cfg, result = built
    assert result.manifest is not None
    assert validate_dataset(result.directory) == []
    loaded = read_dataset(result.directory)
    assert loaded.problems == []
    assert {s.value for s in result.manifest.splits} >= {"smoke", "core", "robust_pr"}
    assert sum(result.manifest.splits.values()) == sum(len(v) for v in loaded.cases.values())


def test_every_stage_has_a_file_and_the_report_counts_dropped_licences(built) -> None:  # type: ignore[no-untyped-def]
    cfg, result = built
    work = Workdir(cfg.work_dir / "pruefstand-de-small-v1")
    for name in STAGES[:-1]:
        assert work.path(name).is_file(), name
        assert work.meta(name) is not None
    assert result.report["dropped_mixed_license"] == 0
    assert (work.root / "build_report.json").is_file()


def test_attack_refusal_and_probe_cases_are_in_the_dataset(built) -> None:  # type: ignore[no-untyped-def]
    _, result = built
    cases = [c for v in read_dataset(result.directory).cases.values() for c in v]
    categories = {c.category for c in cases}
    assert Category.UNANSWERABLE in categories
    assert categories & {
        Category.LEAK_PROBE,
        Category.FILTER_BYPASS,
        Category.SYSTEM_PROMPT_EXTRACTION,
    }
    assert {c.corpus_version for c in cases} == {result.manifest.corpus_version}


def test_robust_pr_has_bases_with_their_perturbed_variants(built) -> None:  # type: ignore[no-untyped-def]
    _, result = built
    cases = read_dataset(result.directory).cases[Split.ROBUST_PR]
    bases = {c.id for c in cases if c.perturbation is None}
    assert len(bases) == 2
    assert all(c.base_id in bases for c in cases if c.perturbation)
    assert any(c.perturbation for c in cases)


def test_bases_are_ranked_by_how_many_perturbations_apply(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    asyncio.run(run_build(cfg, stage="generate", clients=offline_clients()))
    asyncio.run(run_build(cfg, stage="filter", clients=offline_clients()))
    asyncio.run(run_build(cfg, stage="perturb", clients=offline_clients()))
    work = Workdir(cfg.work_dir / "pruefstand-de-small-v1")
    rows = work.read("perturb", TestCase)
    bases = [c for c in rows if c.perturbation is None]
    counts = {b.id: sum(1 for c in rows if c.base_id == b.id and c.perturbation) for b in bases}
    top = work.meta("perturb")
    assert top is not None
    assert top.counters["ranked_top_score"] == max(counts.values())
    kept = work.meta("filter")
    assert kept is not None
    assert top.counters["bases"] == len(bases) == kept.counters["kept"]
    assert kept.counters["total"] == len(candidates())
    assert kept.counters["support_skipped"] == 1  # no support model configured: reported


def test_resume_reruns_only_the_stage_whose_output_was_deleted(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    clients = offline_clients()
    asyncio.run(run_build(cfg, clients=clients))
    work = Workdir(cfg.work_dir / "pruefstand-de-small-v1")
    before = {n: work.path(n).stat().st_mtime_ns for n in STAGES[:-1]}
    work.path("validate").with_suffix(".meta.json").unlink(missing_ok=True)
    (cfg.out_dir / cfg.name / cfg.dataset_version / "dataset_manifest.json").unlink()
    result = asyncio.run(run_build(cfg, resume=True, clients=clients))
    assert result.manifest is not None
    assert {n: work.path(n).stat().st_mtime_ns for n in STAGES[:-1]} == before
    # a changed setting invalidates its stage and the stages after it
    changed = _config(tmp_path, seed=6)
    asyncio.run(run_build(changed, resume=True, clients=clients))
    assert work.path("splits").stat().st_mtime_ns != before["splits"]
    assert work.path("generate").stat().st_mtime_ns != before["generate"]  # seed is in its inputs


def test_a_pair_of_two_share_alike_sources_is_dropped_and_counted() -> None:
    chunks = slice_chunks()
    law = chunks["gii-bgb-622#0"]
    decision = as_chunk(
        chunks["gii-bgb-623#0"], chunk_id="oldp-1#0", doc_id="oldp-1", source="oldp:x"
    )
    quad = as_chunk(
        chunks["gii-bgb-624#0"], chunk_id="gq-1#0", doc_id="gq-1", source="germanquad:x"
    )
    lookup = {c.chunk_id: c for c in (law, decision, quad)}
    base = candidate(law, "Welche Grundkündigungsfrist gilt für Beschäftigte?", "Vier Wochen.")
    hop = base.model_copy(update={"prompt_version": "qa_multi_hop_de_v1"})
    fine = hop.model_copy(update={"extra_chunk_ids": (decision.chunk_id,)})  # law + decision
    mixed = hop.model_copy(
        update={"chunk_id": decision.chunk_id, "extra_chunk_ids": (quad.chunk_id,)}
    )  # oldp + germanquad
    cases, dropped = base_cases([fine, mixed], lookup, "cv")
    assert dropped == 1
    assert [c.license_config for c in cases] == ["oldp_derived"]


def test_unknown_stage_and_missing_model_settings_are_config_errors(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    with pytest.raises(ConfigError, match="unknown stage"):
        asyncio.run(run_build(cfg, stage="nope", clients=offline_clients()))
    no_embed = _config(tmp_path, embed=None)
    asyncio.run(run_build(no_embed, stage="generate", clients=offline_clients()))
    with pytest.raises(ConfigError, match="embedding server"):
        asyncio.run(run_build(no_embed, stage="filter", clients=offline_clients()))
    generate = _config(tmp_path, generation=GenerationConfig(units={"factual": 2}))
    with pytest.raises(ConfigError, match=r"models\.datagen"):
        asyncio.run(run_build(generate, stage="generate", clients=offline_clients()))


async def test_build_dataset_returns_the_manifest(tmp_path: Path) -> None:
    manifest = await build_dataset(_config(tmp_path), clients=offline_clients())
    assert manifest.name == "pruefstand-de-small"
    with pytest.raises(Exception, match="validate stage"):
        await build_dataset(
            _config(tmp_path, out_dir=tmp_path / "other"), stage="splits", clients=offline_clients()
        )


def _generate_config(tmp_path: Path, units: dict[str, int]) -> DatasetBuildConfig:
    models = BuildModels(
        datagen=ModelRef(id="github/openai/gpt-4.1-mini", family="gpt"),
        generator=ModelRef(id="ollama/qwen3.8:27b-q8_0", family="qwen"),
    )
    return _config(tmp_path, models=models, generation=GenerationConfig(units=units))


def test_the_generate_stage_sends_units_keeps_a_ledger_and_merges_only(tmp_path: Path) -> None:
    """Plumbing with the scripted loopback server (D527): requests, ledger, resume, ``--only``."""
    calls: list[str] = []
    with datagen_server() as (base, state):
        clients = BuildClients(
            datagen=client_factory(base, calls),
            local=offline_clients().local,
            embed=offline_clients().embed,
        )
        cfg = _generate_config(tmp_path, {"factual": 1, "comparison": 1})
        asyncio.run(run_build(cfg, stage="generate", clients=clients))
        work = Workdir(cfg.work_dir / "pruefstand-de-small-v1")
        rows = work.read("generate", QACandidate)
        sent = state.posts()
        assert sent >= 2
        assert {r.prompt_version for r in rows} == {"qa_factual_de_v1", "qa_comparison_de_v1"}
        assert (work.root / "generate_ledger.jsonl").is_file()
        assert set(calls) == {"github/openai/gpt-4.1-mini"}
        # a second run finds every unit in the ledger: no new request
        asyncio.run(run_build(cfg, stage="generate", clients=clients))
        assert state.posts() == sent
        # --only keeps the candidates of the prompts it does not regenerate
        asyncio.run(run_build(cfg, stage="generate", only="qa_comparison_de", clients=clients))
        again = work.read("generate", QACandidate)
        assert {r.prompt_version for r in again} == {"qa_factual_de_v1", "qa_comparison_de_v1"}
        with pytest.raises(ConfigError, match="names no configured prompt"):
            asyncio.run(run_build(cfg, stage="generate", only="qa_multi_hop_de", clients=clients))


def test_an_unknown_generation_category_is_a_config_error(tmp_path: Path) -> None:
    cfg = _generate_config(tmp_path, {"poetry": 1})
    with pytest.raises(ConfigError, match="unknown category"):
        asyncio.run(run_build(cfg, stage="generate", clients=offline_clients()))


def test_a_datagen_model_of_the_judge_family_is_refused_before_any_request(tmp_path: Path) -> None:
    models = BuildModels(
        datagen=ModelRef(id="ollama/gemma3:12b", family="gemma"),
        generator=ModelRef(id="ollama/qwen3.8:27b-q8_0", family="qwen"),
    )
    cfg = _config(tmp_path, models=models, generation=GenerationConfig(units={"factual": 1}))
    with pytest.raises(ConfigError, match="datagen"):
        asyncio.run(run_build(cfg, stage="generate", clients=offline_clients()))
