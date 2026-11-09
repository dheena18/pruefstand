"""Judged metrics never move the tier-1 fingerprint, so main's tier-1 baseline stays comparable."""

from pathlib import Path

import pytest
import respx
from contract.adapter_contract import load_openapi_example
from testsupport.pipeline_support import (
    CORPUS_VERSION,
    case_rows,
    mini_config,
    write_dataset,
)
from testsupport.run_builders import make_cases

from pruefstand.core.config import GatePolicy, MetricPolicy, TargetConfig
from pruefstand.core.enums import Split
from pruefstand.metrics.registry import MetricRegistry
from pruefstand.pipeline import run as run_module
from pruefstand.pipeline.gate import run_gate
from pruefstand.pipeline.run import run_eval

POLICY = GatePolicy(
    metrics={
        "context_recall": MetricPolicy(max_drop=0.05),
        "faithfulness": MetricPolicy(max_drop=0.05),
        "answer_correctness": MetricPolicy(max_drop=0.05),
    },
    min_clusters=1,
)


@pytest.fixture
def dataset(tmp_path: Path, router: respx.MockRouter) -> Path:
    router.get("/v1/info").respond(404)
    router.post("/v1/query").respond(200, json=load_openapi_example("query_ok.json"))
    rows = case_rows(make_cases(8, split="smoke"))
    return write_dataset(tmp_path / "ds", {"smoke": rows}, corpus_version=CORPUS_VERSION)


async def test_a_run_with_and_without_judged_metrics_has_one_tier_one_fingerprint(
    dataset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = mini_config(
        target=TargetConfig(type="http", url="http://target.test", timeout_s=5),
        dataset=str(dataset),
        splits=(Split.SMOKE,),
        gate=POLICY,
    )
    monkeypatch.setattr(run_module, "build_registry", MetricRegistry.default)
    old = await run_eval(cfg, tier="pr", out=tmp_path / "old")
    monkeypatch.setattr(run_module, "build_registry", MetricRegistry.full)
    new = await run_eval(cfg, tier="pr", out=tmp_path / "new")
    assert old.manifest.eval_fingerprint == new.manifest.eval_fingerprint
    assert "faithfulness" in new.manifest.metric_versions
    assert "faithfulness" not in old.manifest.metric_versions
    report = run_gate(
        tmp_path / "new" / new.manifest.run_id, tmp_path / "old" / old.manifest.run_id, cfg
    )
    informational = {d.metric for d in report.decisions if d.informational_reason} | {
        s.metric for s in report.notable_slices if s.informational_reason == "tier1_judged"
    }
    assert report.no_baseline is False
    assert informational <= {"faithfulness", "answer_correctness", "context_recall"}


async def test_in_tier_two_the_judged_metric_versions_do_enter_the_fingerprint(
    dataset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PRUEFSTAND_STACK", "a40")
    monkeypatch.setenv("PRUEFSTAND_JUDGE_MODE", "skipped")
    cfg = mini_config(
        target=TargetConfig(type="http", url="http://target.test", timeout_s=5),
        dataset=str(dataset),
        splits=(Split.SMOKE,),
        gate=POLICY,
    )
    monkeypatch.setattr(run_module, "build_registry", MetricRegistry.default)
    old = await run_eval(cfg, tier="pr", out=tmp_path / "old")
    monkeypatch.setattr(run_module, "build_registry", MetricRegistry.full)
    new = await run_eval(cfg, tier="pr", out=tmp_path / "new")
    assert old.manifest.eval_fingerprint != new.manifest.eval_fingerprint
