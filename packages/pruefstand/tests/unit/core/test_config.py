import copy
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from pruefstand.core.config import (
    BaselineStoreConfig,
    BudgetConfig,
    HttpTargetConfig,
    JudgeConfig,
    LLMPolicyConfig,
    ModelRef,
    PruefstandConfig,
    RunnerConfig,
    TargetConfig,
)
from pruefstand.core.enums import Split
from pruefstand.core.errors import ConfigError
from pruefstand.core.schema import export_schemas

GEMMA = {"id": "ollama/gemma3:12b", "family": "gemma"}


def raw() -> dict[str, Any]:
    return copy.deepcopy(
        {
            "version": 1,
            "target": {"type": "http", "url": "http://localhost:8000"},
            "dataset": "datasets/fixtures/slice_v1",
            "splits": ["smoke", "core"],
            "generator_family": "qwen",
            "judge": {"pr": GEMMA, "nightly": GEMMA},
            "gate": {"metrics": {"context_recall": {"max_drop": 0.05}}},
            "budget": {},
            "runner": {},
            "baseline_store": {"type": "local_dir", "path": "baselines"},
        }
    )


def build(mutate: Any = None) -> PruefstandConfig:
    data = raw()
    if mutate is not None:
        mutate(data)
    return PruefstandConfig.model_validate(data)


def test_valid_config_and_defaults() -> None:
    cfg = build()
    assert cfg.splits == (Split.SMOKE, Split.CORE)
    assert cfg.seed == 1234
    assert cfg.llm == LLMPolicyConfig()
    assert cfg.llm.allowed_providers == ("openai_compatible_local", "ollama", "github")
    assert cfg.llm.allow_paid is False
    assert cfg.llm.fallback_judge is None
    assert cfg.budget == BudgetConfig(max_usd_per_run=0.0)
    assert cfg.budget.max_tokens_per_run is None
    assert cfg.budget.max_requests_per_run is None
    assert cfg.runner == RunnerConfig(concurrency=8, timeout_s=60, max_retries=3, backoff_s=1.0)
    assert isinstance(cfg.target, TargetConfig)


def test_config_is_frozen_and_forbids_extra() -> None:
    cfg = build()
    with pytest.raises(ValidationError):
        cfg.seed = 1  # type: ignore[misc]  # frozen model: the assignment is the test
    with pytest.raises(ValidationError):
        build(lambda d: d.update(surprise=1))


# --- family rules (ADR-0009, D74) ---


def test_judge_family_equal_to_generator_is_rejected() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["judge"]["pr"] = {"id": "ollama/qwen3:8b", "family": "qwen"}

    with pytest.raises(
        ConfigError, match=r"judge\.pr: family 'qwen' equals generator_family.*ADR-0009"
    ):
        build(mutate)


def test_nightly_judge_family_equal_to_generator_is_rejected() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["judge"]["nightly"] = {"id": "ollama/qwen3:8b", "family": "qwen"}

    with pytest.raises(ConfigError, match=r"judge\.nightly.*ADR-0009"):
        build(mutate)


def test_per_metric_judge_family_equal_to_generator_is_rejected() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["judge"]["per_metric"] = {"faithfulness": {"id": "ollama/qwen3:8b", "family": "qwen"}}

    with pytest.raises(ConfigError, match=r"judge\.per_metric\.faithfulness.*ADR-0009"):
        build(mutate)


def test_fallback_judge_is_family_checked_too() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["llm"] = {"fallback_judge": {"id": "ollama/qwen3:8b", "family": "qwen"}}

    with pytest.raises(ConfigError, match=r"llm\.fallback_judge.*ADR-0009"):
        build(mutate)


def test_per_metric_other_family_is_ok() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["judge"]["per_metric"] = {
            "faithfulness": {"id": "github/openai/gpt-4.1", "family": "gpt"}
        }

    assert build(mutate).judge.per_metric["faithfulness"].family == "gpt"


def test_per_metric_key_must_be_a_known_metric() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["judge"]["per_metric"] = {"faithfulnes": GEMMA}

    with pytest.raises(ConfigError, match="faithfulnes"):
        build(mutate)


def test_mislabelled_judge_is_rejected() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["judge"]["pr"] = {"id": "ollama/qwen3:8b", "family": "gemma"}

    with pytest.raises(
        ConfigError, match=r"judge\.pr: id looks like 'qwen' but family says 'gemma'"
    ):
        build(mutate)


def test_unknown_id_with_known_family_is_accepted() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["judge"]["pr"] = {"id": "ollama/custom-tag", "family": "gemma"}

    assert build(mutate).judge.pr.id == "ollama/custom-tag"


def test_unknown_generator_family_is_rejected() -> None:
    with pytest.raises(ConfigError, match=r"generator_family.*'foo'.*model_families\.yaml"):
        build(lambda d: d.update(generator_family="foo"))


def test_unknown_judge_family_is_rejected() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["judge"]["pr"] = {"id": "ollama/whatever", "family": "bar"}

    with pytest.raises(ConfigError, match=r"judge\.pr.*'bar'.*model_families\.yaml"):
        build(mutate)


def test_generator_family_is_required() -> None:
    def mutate(d: dict[str, Any]) -> None:
        del d["generator_family"]

    with pytest.raises(ValidationError, match="generator_family"):
        build(mutate)


# --- target, baseline store, runner, budget ---


def test_target_requires_url_and_http_type() -> None:
    with pytest.raises(ValidationError, match="url"):
        build(lambda d: d.update(target={"type": "http"}))
    with pytest.raises(ValidationError, match="type"):
        build(lambda d: d.update(target={"type": "mock", "url": "http://x"}))
    with pytest.raises(ValidationError, match="url"):
        HttpTargetConfig.model_validate({"type": "http"})
    assert HttpTargetConfig(type="http", url="http://x").timeout_s == 60
    assert TargetConfig(url="http://x").type == "http"


def test_target_auth_env_is_a_variable_name() -> None:
    assert TargetConfig(url="http://x", auth_env="TARGET_TOKEN").auth_env == "TARGET_TOKEN"
    with pytest.raises(ValidationError, match="auth_env"):
        TargetConfig(url="http://x", auth_env="Bearer abc def")


def test_baseline_store_validators() -> None:
    with pytest.raises(ConfigError, match=r"local_dir.*path"):
        BaselineStoreConfig(type="local_dir")
    with pytest.raises(ConfigError, match=r"git_branch.*repo"):
        BaselineStoreConfig(type="git_branch")
    with pytest.raises(ConfigError, match="owner/name"):
        BaselineStoreConfig(type="git_branch", repo="not-a-repo")
    store = BaselineStoreConfig(type="git_branch", repo="dheena18/pruefstand-gate")
    assert store.branch == "baselines"
    assert store.data_root is None
    assert BaselineStoreConfig(repo="dheena18/pruefstand-gate").type == "git_branch"
    local = BaselineStoreConfig(type="local_dir", path=Path("b"), data_root=Path("/mnt/pruefstand"))
    assert local.path == Path("b")


def test_runner_and_budget_ranges() -> None:
    with pytest.raises(ValidationError, match="concurrency"):
        RunnerConfig(concurrency=0)
    with pytest.raises(ValidationError, match="max_retries"):
        RunnerConfig(max_retries=-1)
    with pytest.raises(ValidationError, match="max_usd_per_run"):
        BudgetConfig(max_usd_per_run=-1.0)
    assert BudgetConfig(max_usd_per_run=None, max_requests_per_run=10).max_requests_per_run == 10
    with pytest.raises(ValidationError, match="judge"):
        RunnerConfig.model_validate({"judge_max_calls": 10})


def test_judge_config_shape() -> None:
    judge = JudgeConfig(
        pr=ModelRef(id="a", family="gemma"), nightly=ModelRef(id="b", family="gemma")
    )
    assert judge.per_metric == {}
    with pytest.raises(ValidationError, match="family"):
        ModelRef.model_validate({"id": "ollama/gemma3:12b"})


def test_splits_must_not_be_empty() -> None:
    with pytest.raises(ValidationError, match="splits"):
        build(lambda d: d.update(splits=[]))


def test_pruefstand_config_schema_is_registered(tmp_path: Path) -> None:
    names = {p.name for p in export_schemas(tmp_path)}
    assert "pruefstand_config.schema.json" in names
