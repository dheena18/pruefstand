"""Records real reviewer answers for ``test_model_review_cassette.py`` (T4.7a).

Run by ``record_cassettes.sh --review`` on the VM under the GPU lock with the judge loaded. Without
``PRUEFSTAND_RECORD_REVIEW=1`` it is skipped. Nothing is ever written by hand.
"""

import os

import pytest
from testsupport.review_cassettes import CASSETTES, cases, client_with, reviewer_id, sources

from pruefstand.core.config import LLMPolicyConfig, ModelRef
from pruefstand.dataset.model_review import review_with_model
from pruefstand.llm.factory import build_backend

pytestmark = [
    pytest.mark.live,
    pytest.mark.gpu,
    pytest.mark.skipif(
        os.environ.get("PRUEFSTAND_RECORD_REVIEW") != "1",
        reason="set PRUEFSTAND_RECORD_REVIEW=1 (scripts/models/record_cassettes.sh --review)",
    ),
]


async def test_record_the_review_cassettes() -> None:
    model = reviewer_id()
    real = build_backend(ModelRef(id=model, family="gemma"), policy=LLMPolicyConfig())
    outcome = await review_with_model(cases(), sources(), client_with("record", real), model)
    assert not outcome.failed
    assert all(item.reason for item in outcome.items)
    assert len(list(CASSETTES.glob("*.json"))) >= 4  # the attack-free cases with a model call
