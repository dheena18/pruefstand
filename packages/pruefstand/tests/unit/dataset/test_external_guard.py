"""Datagen data guard and model rules (ADR-0019, D330, D355): public text only, never qwen/gemma."""

import numpy as np
import pytest
from testsupport.qa_support import (
    DATAGEN,
    SECOND,
    as_chunk,
    chunk,
    datagen_server,
    make_client,
)

from pruefstand.core.config import LLMPolicyConfig, ModelRef
from pruefstand.core.errors import ConfigError, PolicyViolation
from pruefstand.core.ids import DocId, TenantId
from pruefstand.core.models.attacks import Canary, CanaryRegistry
from pruefstand.core.models.llm import LLMRequest, LLMRole, Message
from pruefstand.dataset.datagen_guard import check_datagen_model, datagen_policy
from pruefstand.dataset.generate import GenStats, generate_qa
from pruefstand.llm.policy import LLMPolicy, provider_of


def _rng() -> np.random.Generator:
    return np.random.default_rng(7)


def _request() -> LLMRequest:
    return LLMRequest(
        role=LLMRole.DATAGEN,
        model=DATAGEN,
        messages=(Message(role="user", content="Hallo"),),
        prompt_id="qa_factual_de",
        prompt_version="v1",
    )


def test_datagen_policy_allows_public_datagen_to_github_only() -> None:
    policy = datagen_policy(None)
    policy.check(_request(), provider_of(DATAGEN))
    with pytest.raises(PolicyViolation):
        policy.check(_request().model_copy(update={"model": "mistral/large"}), "mistral")


def test_a_datagen_request_through_a_default_policy_is_refused() -> None:
    plain = LLMPolicy(LLMPolicyConfig())
    with pytest.raises(PolicyViolation, match="datagen"):
        plain.check(_request(), "github")


@pytest.mark.parametrize("family", ["qwen", "gemma"])
def test_a_datagen_model_of_the_generator_or_judge_family_is_refused(family: str) -> None:
    with pytest.raises(ConfigError, match=family):
        check_datagen_model(ModelRef(id="github/some/model", family=family))


def test_family_is_read_from_the_id_when_not_given() -> None:
    assert check_datagen_model(DATAGEN) == "gpt"
    assert check_datagen_model(SECOND) == "llama"
    with pytest.raises(ConfigError, match="qwen"):
        check_datagen_model("github/alibaba/qwen3-32b")
    with pytest.raises(ConfigError, match="gemma"):
        check_datagen_model("github/google/gemma-3")


def test_a_declared_family_that_contradicts_the_id_is_refused() -> None:
    with pytest.raises(ConfigError, match="family"):
        check_datagen_model(ModelRef(id=DATAGEN, family="llama"))


def test_a_local_datagen_model_is_refused() -> None:
    with pytest.raises(ConfigError, match=r"no local datagen model \(ADR-0019\)"):
        check_datagen_model("ollama/llama3.3:70b")
    with pytest.raises(ConfigError, match="GitHub Models"):
        check_datagen_model("mistral/mistral-large")


async def test_generate_refuses_a_forbidden_model_before_any_call() -> None:
    with datagen_server() as (base, state):
        client, _ = make_client(base)
        with pytest.raises(ConfigError, match="qwen"):
            await generate_qa(
                [chunk("gii-bgb-622#1")],
                client,
                "github/alibaba/qwen3-32b",
                "qa_factual_de_v1",
                _rng(),
            )
    assert state.posts() == 0


async def test_private_and_attack_chunks_are_never_sent() -> None:
    private = [chunk("syn-km-kanzleihandbuch#0"), chunk("syn-inj-shared-probezeit-tabelle#0")]
    stats = GenStats()
    with datagen_server() as (base, state):
        client, _ = make_client(base)
        got = await generate_qa(private, client, DATAGEN, "qa_factual_de_v1", _rng(), stats=stats)
    assert got == []
    assert state.posts() == 0
    assert stats.counts["skipped_private"] == 2


async def test_a_chunk_with_a_registered_canary_is_blocked_by_the_client_guard() -> None:
    token = "-".join(["CANARY", "KM", "0f3a9c"])
    leaked = as_chunk(chunk("gii-bgb-622#1"), text=chunk("gii-bgb-622#1").text + f"\nAkte {token}")
    canary = Canary(
        doc_id=DocId("syn-km-x"),
        tenant=TenantId("kanzlei_mueller"),
        token=token,
        fact=None,
        kind="token",
        probe_question="Wie lautet die Akte?",
        forbidden_answer=token,
    )
    registry = CanaryRegistry(canaries=(canary,))
    stats = GenStats()
    with datagen_server() as (base, state):
        client, _ = make_client(base, canaries=registry)
        got = await generate_qa([leaked], client, DATAGEN, "qa_factual_de_v1", _rng(), stats=stats)
    assert got == []
    assert state.posts() == 0
    assert stats.counts["skipped_private"] == 1
