"""Block, stratum and judged-subset selection of ``run_eval`` (R12 N1.2, R13 P4.3 / P3.4)."""

import json
import re
from pathlib import Path
from typing import Any

import pytest
import respx
from contract.adapter_contract import load_openapi_example
from testsupport.pipeline_support import CORPUS_VERSION, case_rows, synthetic_config, write_dataset
from testsupport.run_builders import make_case
from testsupport.runner_support import SpyPool, StubJudgedMetric

from pruefstand.core.config.gate import JUDGED_METRICS
from pruefstand.core.enums import Split
from pruefstand.core.errors import ConfigError
from pruefstand.core.fingerprint import eval_fingerprint
from pruefstand.core.models.metric import MetricStatus
from pruefstand.core.models.run import RunResults
from pruefstand.metrics.registry import MetricRegistry
from pruefstand.pipeline import run as run_module
from pruefstand.pipeline.fingerprints import calibration_epoch
from pruefstand.pipeline.run import run_eval
from pruefstand.runner.runner import Runner

# Cases: 3 blocks of 4 cases, 5 refusal-stratum cases (category unanswerable, block None).
FULL: list[dict[str, Any]] = []
for block in range(3):
    for j in range(4):
        i = 10 * block + j
        FULL.append(case_rows([make_case(i, split="full", block=block, question=f"Frage {i}")])[0])
for j in range(5):
    i = 100 + j
    FULL.append(
        case_rows(
            [
                make_case(
                    i,
                    split="full",
                    category="unanswerable",
                    expect_refusal=True,
                    gold_doc_ids=[],
                    gold_citations=[],
                    reference_answer=None,
                    question=f"Frage {i}",
                )
            ]
        )[0]
    )


def sent(router: respx.MockRouter, route: str = "/v1/query") -> list[int]:
    """The numbers of the questions that reached ``route`` (question text is ``Frage <n>``)."""
    found = [c.request for c in router.calls if c.request.url.path == route]
    return sorted(_number(json.loads(r.content)["question"]) for r in found)


def _number(question: str) -> int:
    match = re.search(r"\d+", question)
    assert match is not None
    return int(match[0])


@pytest.fixture
def full_dataset(tmp_path: Path, router: respx.MockRouter) -> Path:
    router.get("/v1/info").respond(404)
    router.post("/v1/query").respond(200, json=load_openapi_example("query_ok.json"))
    return write_dataset(tmp_path / "ds", {"full": FULL})


async def run_full(dataset: Path, tmp_path: Path, **kwargs: Any) -> RunResults:
    cfg = synthetic_config(dataset, (Split.FULL,))
    return await run_eval(cfg, tier="pr", out=tmp_path / "runs", **kwargs)


async def test_block_one_sends_block_one_and_the_refusal_stratum(
    full_dataset: Path, tmp_path: Path, router: respx.MockRouter
) -> None:
    results = await run_full(full_dataset, tmp_path, block=1)
    assert sent(router) == [10, 11, 12, 13, 100, 101, 102, 103, 104]
    assert results.manifest.block == 1
    assert results.manifest.n_cases == 9


async def test_fingerprints_differ_by_block(full_dataset: Path, tmp_path: Path) -> None:
    prints = [
        (await run_full(full_dataset, tmp_path / str(b), block=b)).manifest.eval_fingerprint
        for b in (0, 1, None)
    ]
    assert len(set(prints)) == 3


async def test_stratum_refusal_runs_only_the_refusal_cases(
    full_dataset: Path, tmp_path: Path, router: respx.MockRouter
) -> None:
    refusal = await run_full(full_dataset, tmp_path / "r", stratum="refusal")
    assert sent(router) == [100, 101, 102, 103, 104]
    assert refusal.manifest.stratum == "refusal"
    everything = await run_full(full_dataset, tmp_path / "a")
    assert everything.manifest.stratum == "all"
    assert refusal.manifest.eval_fingerprint != everything.manifest.eval_fingerprint


async def test_stratum_blocks_with_a_block_runs_that_block_only(
    full_dataset: Path, tmp_path: Path, router: respx.MockRouter
) -> None:
    results = await run_full(full_dataset, tmp_path, stratum="blocks", block=1)
    assert sent(router) == [10, 11, 12, 13]
    assert (results.manifest.stratum, results.manifest.block) == ("blocks", 1)


async def test_stratum_blocks_without_a_block_runs_all_three_blocks(
    full_dataset: Path, tmp_path: Path, router: respx.MockRouter
) -> None:
    await run_full(full_dataset, tmp_path, stratum="blocks")
    assert sent(router) == [0, 1, 2, 3, 10, 11, 12, 13, 20, 21, 22, 23]


async def test_stratum_all_without_a_block_runs_everything(
    full_dataset: Path, tmp_path: Path, router: respx.MockRouter
) -> None:
    await run_full(full_dataset, tmp_path)
    assert len(sent(router)) == 17


async def test_refusal_stratum_with_a_block_is_refused(full_dataset: Path, tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="refusal"):
        await run_full(full_dataset, tmp_path, stratum="refusal", block=1)


async def test_block_and_stratum_need_exactly_the_full_split(
    full_dataset: Path, tmp_path: Path
) -> None:
    cfg = synthetic_config(full_dataset, (Split.CORE,))
    for kwargs in ({"stratum": "refusal"}, {"stratum": "blocks"}, {"block": 1}):
        with pytest.raises(ConfigError, match="full"):
            await run_eval(cfg, tier="pr", out=tmp_path / "runs", **kwargs)
    both = synthetic_config(full_dataset, (Split.FULL, Split.CORE))
    with pytest.raises(ConfigError, match="full"):
        await run_eval(both, tier="pr", out=tmp_path / "runs", block=1)


async def test_block_out_of_range_is_refused(full_dataset: Path, tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="block"):
        await run_full(full_dataset, tmp_path, block=3)


async def test_a_selection_that_matches_no_case_is_refused(
    tmp_path: Path, router: respx.MockRouter
) -> None:
    router.get("/v1/info").respond(404)
    only_refusal = [r for r in FULL if r["category"] == "unanswerable"]
    dataset = write_dataset(tmp_path / "ds", {"full": only_refusal})
    with pytest.raises(ConfigError, match="no case"):
        await run_full(dataset, tmp_path, stratum="blocks")


async def test_default_stratum_keeps_the_fingerprint_of_runs_before_it_existed(
    full_dataset: Path, tmp_path: Path
) -> None:
    m = (await run_full(full_dataset, tmp_path)).manifest
    expected = eval_fingerprint(
        dataset_name=m.dataset_name,
        dataset_version=m.dataset_version,
        splits=m.splits,
        judge_models={},
        judge_prompt_versions={},
        judge_serving={},
        judge_epoch=calibration_epoch(),  # T5.4 ships calibration_status.yaml (epoch 1)
        metric_versions={k: v for k, v in m.metric_versions.items() if k not in JUDGED_METRICS},
        corpus_version=CORPUS_VERSION,
        block=None,
        judged_subset=False,
    )  # tier 1: the informational judged metrics stay out of the fingerprint (D810)
    assert m.eval_fingerprint == expected


# --- judged subset (R13 P3.4) ---------------------------------------------------------------

CORE: list[dict[str, Any]] = []
for i in range(6):  # answerable; cases 0 and 1 are in the judged subset
    CORE.append(
        case_rows([make_case(i, split="core", judged_subset=i < 2, question=f"Frage {i}")])[0]
    )
for i in (6, 7):
    CORE.append(
        case_rows(
            [
                make_case(
                    i,
                    split="core",
                    category="unanswerable",
                    expect_refusal=True,
                    question=f"Frage {i}",
                    gold_doc_ids=[],
                    gold_citations=[],
                    reference_answer=None,
                )
            ]
        )[0]
    )
for i in (8, 9):
    CORE.append(
        case_rows(
            [
                make_case(
                    i,
                    split="core",
                    category="injection",
                    injection_marker="PWNED-0000",
                    question=f"Frage {i}",
                    gold_doc_ids=[],
                    gold_citations=[],
                    reference_answer=None,
                )
            ]
        )[0]
    )


@pytest.fixture
def core_dataset(tmp_path: Path, router: respx.MockRouter) -> Path:
    router.get("/v1/info").respond(404)
    router.post("/v1/query").respond(200, json=load_openapi_example("query_ok.json"))
    router.post("/v1/retrieve").respond(200, json=load_openapi_example("retrieve_ok.json"))
    return write_dataset(tmp_path / "core", {"core": CORE})


async def test_judged_subset_is_recorded_and_changes_the_fingerprint(
    core_dataset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[bool] = []
    original = Runner.run

    async def spy(self: Runner, cases: Any, **kwargs: Any) -> RunResults:
        seen.append(kwargs["judged_subset"])
        return await original(self, cases, **kwargs)

    monkeypatch.setattr(Runner, "run", spy)
    cfg = synthetic_config(core_dataset, (Split.CORE,))
    plain = await run_eval(cfg, tier="pr", out=tmp_path / "a")
    subset = await run_eval(cfg, tier="pr", out=tmp_path / "b", judged_subset=True)
    assert seen == [False, True]
    assert subset.manifest.judged_subset is True
    assert plain.manifest.judged_subset is False
    assert subset.manifest.eval_fingerprint != plain.manifest.eval_fingerprint


async def test_judged_subset_needs_the_core_split(full_dataset: Path, tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="core"):
        await run_full(full_dataset, tmp_path, judged_subset=True)


async def test_judged_subset_generates_only_subset_answerable_and_security_cases(
    core_dataset: Path, tmp_path: Path, router: respx.MockRouter
) -> None:
    cfg = synthetic_config(core_dataset, (Split.CORE,))
    results = await run_eval(cfg, tier="pr", out=tmp_path / "runs", judged_subset=True)
    assert sent(router, "/v1/query") == [0, 1, 6, 7, 8, 9]
    assert sent(router, "/v1/retrieve") == [2, 3, 4, 5]
    modes = {str(r.case_id): r.mode for r in results.records}
    assert [modes[f"law-{i:04d}"] for i in range(10)] == ["answer"] * 2 + ["retrieve"] * 4 + [
        "answer"
    ] * 4


async def test_judged_metrics_run_only_on_subset_cases(
    core_dataset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pool = SpyPool()
    monkeypatch.setattr(
        run_module,
        "build_registry",
        lambda: MetricRegistry([*MetricRegistry.default().all(), StubJudgedMetric()]),
    )
    monkeypatch.setattr(run_module, "build_judge_pool", lambda cfg, mode, **kwargs: pool)
    monkeypatch.setenv("PRUEFSTAND_JUDGE_MODE", "local")
    cfg = synthetic_config(core_dataset, (Split.CORE,))
    results = await run_eval(cfg, tier="pr", out=tmp_path / "runs", judged_subset=True)
    by_case = {str(s.case.id): {v.metric: v for v in s.values} for s in results.values}
    for i in range(10):
        value = by_case[f"law-{i:04d}"]["faithfulness"]
        if i < 2:
            assert value.status is MetricStatus.OK
        elif i < 6:
            assert value.status is MetricStatus.NOT_APPLICABLE
            assert value.details["reason"] == "not_in_judged_subset"
    assert results.manifest.counts.get("judge_skipped", 0) == 0
