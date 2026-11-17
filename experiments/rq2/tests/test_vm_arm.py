"""T5.4e skeleton: item plan, session split and preflight (real calibration sets, no model).

The judge answers are covered by REAL recorded exchanges of the VM model in
``tests/cassettes/vm_judge/`` (recorded in plan step 2, after #165 / #166); until then that test
is skipped.
"""

import asyncio
import importlib.util
from collections import Counter
from pathlib import Path

import pytest
from rq2.rq2_config import REPO, load_config
from rq2.run_judges import CALIBRATION_NONCE
from rq2.vm_arm import VM_JUDGE, cassette_items, preflight, sessions, vm_items

from pruefstand.core.config import LLMPolicyConfig
from pruefstand.core.errors import ConfigError
from pruefstand.judges.factory import PROMPT_ROOT
from pruefstand.judges.judge import Judge
from pruefstand.judges.output import make_task
from pruefstand.llm.budget import Budget
from pruefstand.llm.cassettes import CassetteRecorder
from pruefstand.llm.client import LLMClient
from pruefstand.llm.policy import LLMPolicy
from pruefstand.llm.prompts import PromptRegistry
from pruefstand.llm.recorder import CallRecorder

CFG = load_config(REPO / "experiments/rq2/configs/rq2_judges.yaml")
CASSETTES = Path(__file__).parent / "cassettes" / "vm_judge"


def test_the_item_plan_is_seeded_and_keeps_the_strata() -> None:
    # MEMERAG joins the plan where data/derived/memerag_de exists (the VM model is local, D1283)
    first = vm_items(CFG, 300)
    assert [i.item_id for _, i in first] == [i.item_id for _, i in vm_items(CFG, 300)]
    per_set = Counter(name for name, _ in first if name != "memerag")
    assert per_set == {
        "faithfulness_constructed": 300,
        "correctness": 300,
        "refusal": 300,
        "consistency": 300,
    }
    assert all(i.calib_split == "test" for _, i in first)
    hard = {name: sum(1 for n, i in first if n == name and i.hard_negative) for name in per_set}
    assert all(v > 0 for k, v in hard.items() if k != "refusal")  # strata kept


def test_sessions_cover_every_call_once_within_the_launcher_limit() -> None:
    plan = sessions(1200, 45.0)
    assert [len(r) for r in plan] == [256, 256, 256, 256, 176]
    assert [k for r in plan for k in r] == list(range(1200))
    assert sessions(0, 45.0) == []
    with pytest.raises(ValueError, match="positive"):
        sessions(10, 0.0)
    with pytest.raises(ValueError, match="does not fit"):
        sessions(10, 20_000.0)


@pytest.mark.skipif(
    importlib.util.find_spec("pruefstand.dataset.vm_datagen") is not None,
    reason="PR #166 is merged: the preflight passes",
)
def test_the_real_run_is_refused_until_the_backend_prs_are_merged() -> None:
    with pytest.raises(ConfigError, match="#165 and PR #166"):
        preflight()


@pytest.mark.skipif(
    not any(CASSETTES.glob("*.json")),
    reason="no VM judge cassettes yet: plan step 2 records them (after #165 / #166)",
)
def test_recorded_vm_answers_parse_to_raw_scores() -> None:
    policy = LLMPolicyConfig()
    backend = CassetteRecorder(CASSETTES, "replay").wrap(None)
    client = LLMClient(backend, None, Budget(None, None), CallRecorder(), LLMPolicy(policy))
    judge = Judge(client, VM_JUDGE, PromptRegistry([PROMPT_ROOT]), nonce_key=CALIBRATION_NONCE)
    items = cassette_items(CFG)  # the publishable sets only: no MEMERAG text in a cassette
    for item in items:
        verdict = asyncio.run(judge.score(make_task(item.metric, **item.inputs)))
        assert verdict.raw_score is not None
