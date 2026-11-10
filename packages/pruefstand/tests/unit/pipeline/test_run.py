"""``run_eval``: config + cases -> adapter -> runner -> completed manifest -> run directory (S2)."""

import json
import subprocess
from pathlib import Path

import pytest
import respx
from contract.adapter_contract import load_openapi_example
from testsupport.pipeline_support import (
    CORPUS_VERSION,
    case_rows,
    mini_config,
    synthetic_config,
    write_dataset,
)
from testsupport.run_builders import make_cases

from pruefstand.core.config_loader import load_config
from pruefstand.core.enums import Split
from pruefstand.core.errors import ConfigError, CorpusMismatch
from pruefstand.core.fingerprint import target_fingerprint
from pruefstand.core.hashing import stable_hash
from pruefstand.core.models.target import TargetInfo
from pruefstand.pipeline.fingerprints import calibration_epoch
from pruefstand.pipeline.run import run_eval
from pruefstand.store.artifacts import ArtifactStore

SHA = "0123456789abcdef0123456789abcdef01234567"


@pytest.fixture
def dataset(tmp_path: Path) -> Path:
    return write_dataset(tmp_path / "ds", {"smoke": case_rows(make_cases(4, split="smoke"))})


def serve(router: respx.MockRouter, *, corpus_version: str = CORPUS_VERSION) -> None:
    info = {**load_openapi_example("info.json"), "corpus_version": corpus_version}
    router.get("/v1/info").respond(200, json=info)
    router.post("/v1/query").respond(200, json=load_openapi_example("query_ok.json"))


async def test_writes_a_readable_run_directory_with_a_completed_manifest(
    dataset: Path, tmp_path: Path, router: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    serve(router)
    monkeypatch.setenv("GITHUB_SHA", SHA)
    monkeypatch.setenv("GITHUB_REF", "refs/pull/7/merge")
    cfg = synthetic_config(dataset, (Split.SMOKE,), seed=99)
    results = await run_eval(cfg, tier="nightly", out=tmp_path / "runs")
    m = results.manifest
    run_dir = tmp_path / "runs" / m.run_id
    assert {p.name for p in run_dir.iterdir()} >= {"run.json", "results.parquet", "responses.jsonl"}
    stored = ArtifactStore(tmp_path / "runs").read_run(run_dir).results
    assert stored.manifest.model_copy(update={"artifact_sha256": {}}) == m
    assert set(stored.manifest.artifact_sha256) >= {"results.parquet", "responses.jsonl"}
    assert (m.dataset_name, m.dataset_version, m.n_cases, m.seed) == ("tmpset", "v1", 4, 99)
    assert (m.git_sha, m.git_ref, m.workload, m.stack) == (
        SHA,
        "refs/pull/7/merge",
        "nightly",
        "live",
    )
    assert m.config_hash == stable_hash(cfg)
    assert m.eval_fingerprint
    assert m.eval_fingerprint != m.target_fingerprint
    assert m.target is not None
    assert m.target_fingerprint == target_fingerprint(m.target, url="", run_id="")
    assert m.complete is True
    assert set(m.metric_versions) >= {"context_recall", "tenant_leak"}
    assert m.judge_models == {}
    assert m.judge_prompt_versions == {}
    assert m.judge_epoch == calibration_epoch()  # T5.4 ships calibration_status.yaml


async def test_corpus_mismatch_aborts_before_any_query(
    dataset: Path, tmp_path: Path, router: respx.MockRouter
) -> None:
    serve(router, corpus_version="other-v9")
    cfg = synthetic_config(dataset, (Split.SMOKE,))
    with pytest.raises(CorpusMismatch, match="other-v9"):
        await run_eval(cfg, tier="pr", out=tmp_path / "runs")
    assert [c for c in router.calls if c.request.url.path == "/v1/query"] == []
    (run_dir,) = (tmp_path / "runs").iterdir()
    stored = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert stored["stop_reason"] == "aborted"
    assert stored["complete"] is False
    assert stored["counts"]["corpus_mismatch"] == 1
    assert stored["splits"] == ["smoke"]


async def test_an_opaque_target_continues(
    dataset: Path, tmp_path: Path, router: respx.MockRouter
) -> None:
    serve(router)
    router.get("/v1/info").respond(404)
    results = await run_eval(
        synthetic_config(dataset, (Split.SMOKE,)), tier="pr", out=tmp_path / "r"
    )
    assert results.manifest.target is None
    assert results.manifest.complete is True


async def test_hf_datasets_raise_a_config_error(tmp_path: Path) -> None:
    cfg = mini_config(dataset="hf://x/y@v1", splits=(Split.SMOKE,))
    with pytest.raises(ConfigError, match=r"T4\.7b"):
        await run_eval(cfg, tier="pr", out=tmp_path / "runs")


async def test_rq1_runs_only_in_the_bench_tier(tmp_path: Path, router: respx.MockRouter) -> None:
    serve(router)
    rows = case_rows(make_cases(2, split="rq1"))
    cfg = synthetic_config(write_dataset(tmp_path / "ds", {"rq1": rows}), (Split.RQ1,))
    with pytest.raises(ConfigError, match="rq1"):
        await run_eval(cfg, tier="pr", out=tmp_path / "pr")
    results = await run_eval(cfg, tier="bench", out=tmp_path / "bench")
    assert results.manifest.workload == "bench"


async def test_git_facts_ignore_malformed_environment(
    dataset: Path, tmp_path: Path, router: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    serve(router)
    monkeypatch.setenv("GITHUB_SHA", "not a sha\nwith newline")
    monkeypatch.setenv("GITHUB_REF", "x" * 5000)
    event = tmp_path / "event.json"
    event.write_text('{"pull_request": {"number": "7; rm -rf"}}', encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    monkeypatch.setattr(subprocess, "run", _no_git)
    m = (
        await run_eval(synthetic_config(dataset, (Split.SMOKE,)), tier="pr", out=tmp_path / "r")
    ).manifest
    assert (m.git_sha, m.git_ref, m.pr_number) == (None, None, None)


def _no_git(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
    message = "git"
    raise FileNotFoundError(message)


async def test_pr_number_comes_from_the_event_file(
    dataset: Path, tmp_path: Path, router: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    serve(router)
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"pull_request": {"number": 42}}), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    m = (
        await run_eval(synthetic_config(dataset, (Split.SMOKE,)), tier="pr", out=tmp_path / "r")
    ).manifest
    assert m.pr_number == 42


async def test_an_oversized_event_file_is_ignored(
    dataset: Path, tmp_path: Path, router: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    serve(router)
    event = tmp_path / "event.json"
    event.write_text(
        '{"pull_request": {"number": 42}, "pad": "' + "x" * 3_000_000 + '"}', encoding="utf-8"
    )
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    m = (
        await run_eval(synthetic_config(dataset, (Split.SMOKE,)), tier="pr", out=tmp_path / "r")
    ).manifest
    assert m.pr_number is None


async def test_the_target_fingerprint_is_the_core_one(
    dataset: Path, tmp_path: Path, router: respx.MockRouter
) -> None:
    serve(router)
    m = (
        await run_eval(synthetic_config(dataset, (Split.SMOKE,)), tier="pr", out=tmp_path / "r")
    ).manifest
    info = TargetInfo.model_validate(
        load_openapi_example("info.json") | {"corpus_version": CORPUS_VERSION}
    )
    assert m.target_fingerprint == target_fingerprint(info, url="", run_id="")


def test_the_committed_mini_config_loads() -> None:
    cfg = load_config(Path(__file__).resolve().parents[5] / "examples" / "live" / "mini.yaml")
    assert cfg.dataset == "datasets/fixtures/mini_v0"
