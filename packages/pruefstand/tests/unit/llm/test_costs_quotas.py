"""Costs (free providers, GPU seconds) and the quota table (S7)."""

import asyncio

import pytest
from testsupport.gpu_files import SHIPPED_CATALOGUE

from pruefstand.core.errors import BudgetExceeded, ConfigError
from pruefstand.core.models.llm import LLMResponse
from pruefstand.core.models.target import Usage
from pruefstand.llm.budget import Budget
from pruefstand.llm.costs import configured_providers, cost_usd, gpu_seconds, quota_for


def _resp() -> LLMResponse:
    return LLMResponse(
        text="x", model="github/x", usage=Usage(prompt_tokens=5, completion_tokens=1),
        cost_usd=0.0, latency_ms=1.0, cached=False,
    )  # fmt: skip


def test_every_configured_provider_costs_nothing() -> None:
    providers = configured_providers()
    assert {"ollama", "github", "openai_compatible_local"} <= providers
    for provider in providers:
        assert cost_usd(provider, Usage(prompt_tokens=1000, completion_tokens=1000)) == 0.0


def test_an_unpriced_provider_is_a_config_error() -> None:
    with pytest.raises(ConfigError, match="anthropic"):
        cost_usd("anthropic", Usage(prompt_tokens=1, completion_tokens=1))


def test_ollama_models_use_gpu_seconds_by_server(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRUEFSTAND_GPU_CATALOGUE", str(SHIPPED_CATALOGUE))
    assert gpu_seconds("ollama/gemma3:12b", 2000.0) == pytest.approx(2.0)
    assert gpu_seconds("ollama/qwen3.8:27b-q8_0", 500.0) > 0
    assert gpu_seconds("github/x", 5000.0) == 0.0


def test_the_request_cap_refuses_a_reservation_and_a_bare_charge() -> None:
    async def go() -> None:
        budget = Budget(max_usd=0.0, max_tokens=None, max_requests=3)
        assert await budget.reserve(3) is True
        assert await budget.reserve(1) is False
        for _ in range(3):
            budget.charge(_resp())
        with pytest.raises(BudgetExceeded):
            budget.charge(_resp())

    asyncio.run(go())


def test_quotas_are_loaded_per_github_model() -> None:
    quota = quota_for("github/openai/gpt-4.1-mini")
    assert quota is not None
    assert quota.requests_per_minute > 0
    assert quota.requests_per_day > 0
    assert quota_for("github/unlisted/model") is None
    assert quota_for("ollama/gemma3:12b") is None
