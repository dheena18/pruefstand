"""Canary registry and scope of the judges (review M2, B1): fail closed for any external judge."""

from pathlib import Path
from typing import Any

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
from testsupport.run_builders import make_cases, make_manifest
from testsupport.runner_support import SpyPool

from pruefstand.core.config import JudgeConfig, LLMPolicyConfig, ModelRef
from pruefstand.core.enums import Split
from pruefstand.core.errors import StoreError
from pruefstand.core.ids import DocId, TenantId
from pruefstand.core.models.attacks import Canary, CanaryRegistry
from pruefstand.pipeline import judging as judging_module
from pruefstand.pipeline import run as run_module
from pruefstand.pipeline.judging import load_canaries
from pruefstand.pipeline.run import run_eval
from pruefstand.runner.runner import Runner
from pruefstand.store.promote import flagged_reason

LOCAL = ModelRef(id="ollama/gemma3:12b", family="gemma")
GITHUB = ModelRef(id="github/openai/gpt-4.1-mini", family="gpt")
ALLOWED = ("openai_compatible_local", "ollama", "github")


def cfg_with(pr: ModelRef, fallback: ModelRef | None = None) -> Any:
    return mini_config(
        judge=JudgeConfig(pr=pr, nightly=pr),
        llm=LLMPolicyConfig(allowed_providers=ALLOWED, fallback_judge=fallback),
    )


@pytest.fixture
def no_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(**_: object) -> CanaryRegistry:
        message = "no registry"
        raise StoreError(message)

    monkeypatch.setattr(judging_module, "load_canary_registry", missing)


def test_a_purely_local_setup_may_run_without_a_registry(no_registry: None) -> None:
    registry = load_canaries(cfg_with(LOCAL))
    assert registry is not None
    assert registry.canaries == ()


def test_an_external_judge_without_a_registry_fails_closed(no_registry: None) -> None:
    assert load_canaries(cfg_with(GITHUB)) is None


def test_a_github_fallback_behind_a_local_judge_fails_closed_too(no_registry: None) -> None:
    assert load_canaries(cfg_with(LOCAL, fallback=GITHUB)) is None


async def scope_of(
    cfg: Any,
    tmp_path: Path,
    router: respx.MockRouter,
    monkeypatch: pytest.MonkeyPatch,
    *,
    registry_found: bool = True,
) -> tuple[Any, list[object]]:
    router.get("/v1/info").respond(404)
    router.post("/v1/query").respond(200, json=load_openapi_example("query_ok.json"))
    rows = case_rows(make_cases(3, split="smoke"))
    dataset = write_dataset(tmp_path / "ds", {"smoke": rows}, corpus_version=CORPUS_VERSION)
    full = synthetic_config(dataset, (Split.SMOKE,), judge=cfg.judge, llm=cfg.llm)
    token = "-".join(["CANARY", "QX7", "4711"])  # a canary, not a credential
    canary = Canary(
        token=token, tenant=TenantId("kanzlei_a"), doc_id=DocId("d1"), kind="token",
        fact=None, probe_question=None, forbidden_answer=None,
    )  # fmt: skip
    registry = CanaryRegistry(canaries=(canary,))
    built: list[object] = []

    def build(cfg: object, mode: object, **kw: object) -> SpyPool:
        built.append(cfg)
        return SpyPool()

    def load(**_: object) -> CanaryRegistry:
        if not registry_found:
            message = "no registry"
            raise StoreError(message)
        return registry

    monkeypatch.setattr(judging_module, "load_canary_registry", load)
    monkeypatch.setattr(run_module, "build_judge_pool", build)
    monkeypatch.setenv("PRUEFSTAND_STACK", "a40")
    monkeypatch.setenv("PRUEFSTAND_JUDGE_MODE", "local")
    seen: list[Any] = []
    original = Runner.__init__

    def spy(self: Runner, *args: Any, **kwargs: Any) -> None:
        seen.append(kwargs["judge_scope"])
        original(self, *args, **kwargs)

    monkeypatch.setattr(Runner, "__init__", spy)
    await run_eval(full, tier="pr", out=tmp_path / "runs")
    return seen[0], built


async def test_the_local_judge_gets_no_canary_scope(
    tmp_path: Path, router: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    scope, _ = await scope_of(cfg_with(LOCAL), tmp_path, router, monkeypatch)
    assert scope.canaries is None  # D328: canaries may reach the local judge


async def test_an_external_judge_keeps_the_canary_scope(
    tmp_path: Path, router: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    scope, _ = await scope_of(cfg_with(GITHUB), tmp_path, router, monkeypatch)
    assert scope.canaries is not None


async def test_a_tier_two_run_without_a_registry_and_a_github_fallback_builds_no_pool(
    tmp_path: Path, router: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = cfg_with(LOCAL, fallback=GITHUB)
    _, built = await scope_of(cfg, tmp_path, router, monkeypatch, registry_found=False)
    assert built == []  # fail closed: no judge can run unguarded


def test_a_tier_two_run_without_judges_is_not_promotable() -> None:
    skipped = make_manifest(stack="a40", judge_mode="skipped")
    assert flagged_reason(skipped) is not None
    assert "judge" in str(flagged_reason(skipped))
    assert flagged_reason(make_manifest(stack="a40", judge_mode="local")) is None
    assert flagged_reason(make_manifest(stack="live", judge_mode="skipped")) is None
