"""Records real judge responses for ``test_judge_cassette.py``.

Run by ``record_cassettes.sh --judges``. Needs the A40 judge (``OLLAMA_GPU1_URL``, under the GPU
lock). Without ``PRUEFSTAND_RECORD_JUDGES=1`` it is skipped. Nothing is ever written by hand.
"""

import os

import pytest
from testsupport.judge_cassettes import CASSETTES, TASKS, judge_id, judge_with

from pruefstand.core.config import LLMPolicyConfig, ModelRef
from pruefstand.llm.factory import build_backend

pytestmark = [
    pytest.mark.live,
    pytest.mark.gpu,
    pytest.mark.skipif(
        os.environ.get("PRUEFSTAND_RECORD_JUDGES") != "1",
        reason="set PRUEFSTAND_RECORD_JUDGES=1 (scripts/models/record_cassettes.sh --judges)",
    ),
]


async def test_record_the_judge_cassettes() -> None:
    real = build_backend(ModelRef(id=judge_id(), family="gemma"), policy=LLMPolicyConfig())
    judge = judge_with("record", real)
    for task in TASKS:
        verdict = await judge.score(task)
        assert verdict.reason
    assert len(list(CASSETTES.glob("*.json"))) >= len(TASKS)
