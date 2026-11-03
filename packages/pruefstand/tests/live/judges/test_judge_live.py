"""T5.2a: the tier-1 GitHub Models judge on real pairs and the strongest injections.

The shift is informational: tier-1 judged metrics never gate (W1.4).
"""

import os
import sys

import pytest
from testsupport.injection_run import SET, shifts_for

from pruefstand.core.config import LLMPolicyConfig
from pruefstand.core.models.attacks import CanaryRegistry
from pruefstand.judges.factory import PROMPT_ROOT
from pruefstand.judges.judge import Judge
from pruefstand.judges.output import make_task
from pruefstand.judges.robustness import load_items, task_inputs
from pruefstand.llm.backends.litellm import LiteLLMBackend
from pruefstand.llm.budget import Budget
from pruefstand.llm.client import LLMClient
from pruefstand.llm.factory import GH_MODELS_TOKEN_ENV
from pruefstand.llm.policy import LLMPolicy
from pruefstand.llm.prompts import PromptRegistry
from pruefstand.llm.recorder import CallRecorder

pytestmark = [
    pytest.mark.live,
    pytest.mark.network,
    pytest.mark.skipif(
        not os.environ.get(GH_MODELS_TOKEN_ENV), reason=f"{GH_MODELS_TOKEN_ENV} is not set"
    ),
]
MODEL = os.environ.get("PRUEFSTAND_GH_MODELS_TEST_MODEL", "github/openai/gpt-4.1-mini")
STRONGEST = 10


def _judge() -> Judge:
    backend = LiteLLMBackend(
        MODEL,
        api_base="https://models.github.ai/inference",
        api_key_env=GH_MODELS_TOKEN_ENV,
        timeout_s=60,
    )
    policy = LLMPolicy(LLMPolicyConfig(), CanaryRegistry(canaries=()))
    client = LLMClient(backend, None, Budget(0.0, None), CallRecorder(), policy)
    return Judge(client, MODEL, PromptRegistry([PROMPT_ROOT]), nonce_key=b"live-test-nonce-key")


async def test_five_clean_pairs_give_valid_verdicts() -> None:
    judge = _judge()
    for item in load_items(SET)[:5]:
        inputs = task_inputs("answer_correctness", item, injected=False)
        verdict = await judge.score(make_task("answer_correctness", **inputs))
        assert verdict.raw_score in {0, 1, 2}
        assert verdict.score == verdict.raw_score / 2
        assert verdict.reason


async def test_the_strongest_injections_report_a_mean_shift(
    capsys: pytest.CaptureFixture[str],
) -> None:
    items = load_items(SET)[:STRONGEST]
    result = await shifts_for(_judge(), "answer_correctness", items)
    with capsys.disabled():
        sys.stdout.write(
            f"\n[github judge {MODEL}] n={result.n} mean_shift={result.mean_shift:.3f} "
            f"large_shifts={result.large_shifts}\n"
        )
    assert result.n == STRONGEST  # informational: tier-1 judged metrics never gate (W1.4)
