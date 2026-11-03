"""Pass 2 (``--pass validate``): re-checks on the cache with the local judge, no datagen call."""

import json

import pytest
from testsupport.loopback_script import serve_script
from testsupport.qa_support import chunk

from pruefstand.core.config import LLMPolicyConfig
from pruefstand.core.errors import ConfigError
from pruefstand.core.models.dataset import QACandidate
from pruefstand.dataset.generate_validate import check_candidate, validate_candidates
from pruefstand.llm.backends.litellm import LiteLLMBackend
from pruefstand.llm.budget import Budget
from pruefstand.llm.client import LLMClient
from pruefstand.llm.policy import LLMPolicy
from pruefstand.llm.recorder import CallRecorder

EVIDENCE = "1. zwei Jahre bestanden hat, einen Monat zum Ende eines Kalendermonats,"
JUDGE = "openai_compatible_local/judge-test"


def _cand(**changes: object) -> QACandidate:
    fields: dict[str, object] = {
        "question": "Wie lange muss mein Arbeitgeber mir vorher kündigen?",
        "answer": "Einen Monat zum Ende eines Kalendermonats.",
        "citation": "§ 622 Abs. 2 BGB",
        "chunk_id": "gii-bgb-622#1",
        "prompt_version": "qa_factual_de_v1",
        "evidence_span": EVIDENCE,
    }
    return QACandidate.model_validate({**fields, **changes})


CHUNKS = {"gii-bgb-622#1": chunk("gii-bgb-622#1"), "gii-bgb-626#0": chunk("gii-bgb-626#0")}


def test_a_clean_candidate_has_no_problems() -> None:
    assert check_candidate(_cand(), CHUNKS) == ()


def test_deterministic_problems_are_named() -> None:
    assert check_candidate(_cand(chunk_id="gone#0"), CHUNKS) == ("chunk_missing",)
    assert "citation_unparsed" in check_candidate(_cand(citation="irgendwo"), CHUNKS)
    assert "citation_mismatch" in check_candidate(_cand(citation="§ 1 KSchG"), CHUNKS)
    assert "evidence_missing" in check_candidate(_cand(evidence_span=None), CHUNKS)
    assert "evidence_not_in_chunk" in check_candidate(_cand(evidence_span="Erfunden."), CHUNKS)
    assert "answer_empty" in check_candidate(_cand(answer="  "), CHUNKS)


def _judge(base: str) -> LLMClient:
    backend = LiteLLMBackend(JUDGE, api_base=f"{base}/v1", api_key_env=None, timeout_s=30)
    policy = LLMPolicy(LLMPolicyConfig(allowed_providers=("openai_compatible_local",)))
    return LLMClient(backend, None, Budget(None, None), CallRecorder(), policy)


async def test_without_a_judge_only_the_deterministic_checks_run() -> None:
    rows = await validate_candidates([_cand(), _cand(citation="§ 1 KSchG")], CHUNKS, None, None)
    assert [r.problems for r in rows] == [(), ("citation_mismatch",)]
    assert [r.judge_supported for r in rows] == [None, None]


async def test_the_local_judge_verdict_is_recorded_and_sees_only_the_chunk() -> None:
    verdict = json.dumps({"supported": True, "reason": "steht in Abs. 2"}, ensure_ascii=False)
    with serve_script(content=verdict) as (base, state):
        rows = await validate_candidates([_cand()], CHUNKS, _judge(base), JUDGE)
    assert rows[0].judge_supported is True
    assert state.posts() == 1


async def test_an_unsupported_verdict_becomes_a_problem() -> None:
    with serve_script(content=json.dumps({"supported": False, "reason": "falsch"})) as (base, _s):
        rows = await validate_candidates([_cand()], CHUNKS, _judge(base), JUDGE)
    assert rows[0].judge_supported is False
    assert "judge_unsupported" in rows[0].problems


async def test_an_unreadable_verdict_is_a_judge_error_not_a_crash() -> None:
    with serve_script(content="kein json") as (base, _s):
        rows = await validate_candidates([_cand()], CHUNKS, _judge(base), JUDGE)
    assert rows[0].judge_supported is None
    assert "judge_error" in rows[0].problems


async def test_the_judge_must_be_a_local_model() -> None:
    with serve_script() as (base, state), pytest.raises(ConfigError, match="local"):
        await validate_candidates([_cand()], CHUNKS, _judge(base), "github/openai/gpt-4.1-mini")
    assert state.posts() == 0
