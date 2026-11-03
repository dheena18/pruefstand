"""Tasks and judge construction shared by the judge cassette recorder and its replay test."""

from pathlib import Path
from typing import Literal

import yaml

from pruefstand.core.config import LLMPolicyConfig
from pruefstand.core.models.judge import JudgeTask
from pruefstand.core.protocols import LLMBackend
from pruefstand.judges.factory import PROMPT_ROOT
from pruefstand.judges.judge import Judge
from pruefstand.judges.output import make_task
from pruefstand.judges.robustness import load_items, task_inputs
from pruefstand.llm.budget import Budget
from pruefstand.llm.cassettes import CassetteRecorder
from pruefstand.llm.client import LLMClient
from pruefstand.llm.policy import LLMPolicy
from pruefstand.llm.prompts import PromptRegistry
from pruefstand.llm.recorder import CallRecorder

REPO = Path(__file__).resolve().parents[4]
CASSETTES = REPO / "packages" / "pruefstand" / "tests" / "cassettes" / "judges"
SET = REPO / "datasets" / "fixtures" / "judge_injection.jsonl"
KEY = b"cassette-nonce-key"  # fixed, not a secret: the nonce must be reproducible on replay


def judge_id() -> str:
    """The catalogue id of the judge (role ``judge`` of ``infra/gpu/models.yaml``)."""
    data = yaml.safe_load((REPO / "infra/gpu/models.yaml").read_text(encoding="utf-8"))
    return str(next(m["id"] for m in data["models"] if m["role"] == "judge"))


def _tasks() -> tuple[JudgeTask, ...]:
    items = load_items(SET)
    answer, context = items[0], items[30]
    return (
        make_task("faithfulness", **task_inputs("faithfulness", answer, injected=False)),
        make_task("faithfulness", **task_inputs("faithfulness", context, injected=True)),
        make_task("answer_correctness", **task_inputs("answer_correctness", answer, injected=True)),
        make_task(
            "perturbation_consistency",
            frage="Wie lange?",
            referenz="Drei Monate.",
            antwort="Ein Vierteljahr.",
        ),
        make_task(
            "refusal_judged", frage="Wie lange?", antwort="Dazu liegen mir keine Angaben vor."
        ),
    )


TASKS = _tasks()


def judge_with(mode: Literal["record", "replay"], real: LLMBackend | None) -> Judge:
    """Return a judge whose backend records ``real`` or replays the committed cassettes."""
    policy = LLMPolicyConfig()
    backend = CassetteRecorder(CASSETTES, mode).wrap(real)
    client = LLMClient(backend, None, Budget(None, None), CallRecorder(), LLMPolicy(policy))
    return Judge(client, judge_id(), PromptRegistry([PROMPT_ROOT]), nonce_key=KEY)
