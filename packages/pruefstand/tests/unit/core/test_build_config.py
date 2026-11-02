"""TenantPlan, TenantRule and CorpusBuildConfig (T2.5): validation and loading corpus.yaml."""

from pathlib import Path

import pytest
from pydantic import ValidationError
from testsupport.corpus_support import PLAN_FIXTURE, REPO_ROOT

from pruefstand.core.config import CorpusBuildConfig, TenantPlan
from pruefstand.core.config.build import validate_tenant_id
from pruefstand.core.config_loader import load_model
from pruefstand.core.errors import ConfigError
from pruefstand.core.ids import TenantId

T1, T2 = "kanzlei_mueller", "shared_public"


def plan(**changes: object) -> dict[str, object]:
    base: dict[str, object] = {
        "tenants": [T1, T2],
        "rules": [{"tenant": T1, "source": "gii:kschg"}],
    }
    return {**base, **changes}


def test_a_valid_plan() -> None:
    parsed = TenantPlan.model_validate(plan(default_tenant=T2))
    assert parsed.default_tenant == T2
    assert parsed.sources("gii") == ("gii:kschg",)


@pytest.mark.parametrize(
    "bad", ["../x", "a/b", "A", "", "unassigned", "x" * 64, "1abc", "é", "a b", "a.b"]
)
def test_tenant_ids_are_restricted_to_safe_names(bad: str) -> None:
    with pytest.raises(ValueError, match="tenant"):
        validate_tenant_id(bad)
    with pytest.raises(ValidationError):
        TenantPlan.model_validate(plan(tenants=[bad]))


@pytest.mark.parametrize(
    "changes",
    [
        {"tenants": []},
        {"tenants": [T1, T1]},
        {"rules": [{"tenant": "other_tenant", "source": "gii:x"}]},
        {"rules": [{"tenant": T1}]},
        {"rules": [{"tenant": T1, "source": "gii:x"}, {"tenant": T1, "source": "gii:x"}]},
        {"default_tenant": "nobody"},
        {"rules": [{"tenant": T1, "source": "gii:x", "nonsense": 1}]},
        {"rules": [{"tenant": T1, "metadata": {"k": ""}}]},
    ],
)
def test_invalid_plans_are_rejected(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        TenantPlan.model_validate(plan(**changes))


def test_the_plan_is_bounded() -> None:
    rules = [{"tenant": T1, "source": f"gii:l{i}"} for i in range(1_001)]
    with pytest.raises(ValidationError):
        TenantPlan.model_validate(plan(rules=rules))


def test_models_are_frozen_and_forbid_extra_fields() -> None:
    parsed = TenantPlan.model_validate(plan())
    with pytest.raises(ValidationError):
        parsed.default_tenant = TenantId(T1)  # type: ignore[misc]  # frozen: assignment must fail
    with pytest.raises(ValidationError):
        TenantPlan.model_validate(plan(surprise=True))


@pytest.mark.parametrize("path", [REPO_ROOT / "corpus.yaml", PLAN_FIXTURE])
def test_the_committed_corpus_configs_load(path: Path) -> None:
    config = load_model(path, CorpusBuildConfig)
    assert config.version == 1
    assert {r.tenant for r in config.plan.rules} <= set(config.plan.tenants)


def test_load_model_refuses_aliases_symlinks_and_unknown_keys(tmp_path: Path) -> None:
    base = (REPO_ROOT / "corpus.yaml").read_text(encoding="utf-8")
    (tmp_path / "unknown.yaml").write_text(base + "\nsurprise: 1\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="surprise"):
        load_model(tmp_path / "unknown.yaml", CorpusBuildConfig)
    (tmp_path / "alias.yaml").write_text("a: &x 1\nb: *x\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="alias"):
        load_model(tmp_path / "alias.yaml", CorpusBuildConfig)
    link = tmp_path / "link.yaml"
    link.symlink_to(REPO_ROOT / "corpus.yaml")
    with pytest.raises(ConfigError, match="symlink"):
        load_model(link, CorpusBuildConfig)


def test_limits_have_sane_bounds() -> None:
    data = {"plan": plan()}
    for key, value in (("max_tokens", 0), ("max_chunks", 0), ("max_problems", -1), ("version", 2)):
        with pytest.raises(ValidationError):
            CorpusBuildConfig.model_validate({**data, key: value})
