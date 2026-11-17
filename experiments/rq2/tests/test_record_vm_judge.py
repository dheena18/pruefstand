"""Records the VM judge's real answers for the replay test in ``test_vm_arm.py``.

Run by ``record_cassettes.sh --rq2-vm-judge`` while ``vm_llm.sh start 14b`` serves the
model (it holds the host lock). Without ``PRUEFSTAND_RECORD_RQ2_VM_JUDGE=1`` it is skipped. Only the
publishable sets are recorded (``cassette_items``): no MEMERAG text ever reaches a cassette.
"""

import asyncio
import os
from pathlib import Path

import pytest
from rq2.rq2_config import REPO, load_config
from rq2.run_judges import CALIBRATION_NONCE
from rq2.vm_arm import VM_FAMILY, VM_JUDGE, cassette_items

from pruefstand.core.config import LLMPolicyConfig, ModelRef
from pruefstand.core.settings import PruefstandSettings
from pruefstand.dataset.vm_datagen import build_vm_backend
from pruefstand.judges.factory import PROMPT_ROOT
from pruefstand.judges.judge import Judge
from pruefstand.judges.output import make_task
from pruefstand.llm.budget import Budget
from pruefstand.llm.cassettes import CassetteRecorder
from pruefstand.llm.client import LLMClient
from pruefstand.llm.policy import LLMPolicy
from pruefstand.llm.prompts import PromptRegistry
from pruefstand.llm.recorder import CallRecorder

# record_cassettes.sh records into a temp dir (PRUEFSTAND_RQ2_VM_CASSETTES) and replaces the
# committed cassettes only on success, so a failed recording never loses them
CASSETTES = Path(
    os.environ.get("PRUEFSTAND_RQ2_VM_CASSETTES")
    or Path(__file__).parent / "cassettes" / "vm_judge"
)
pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("PRUEFSTAND_RECORD_RQ2_VM_JUDGE") != "1",
        reason="set PRUEFSTAND_RECORD_RQ2_VM_JUDGE=1 (record_cassettes.sh --rq2-vm-judge)",
    ),
]


def test_record_the_vm_judge_cassettes() -> None:
    real = build_vm_backend(
        ModelRef(id=VM_JUDGE, family=VM_FAMILY), PruefstandSettings().datagen_base_url
    )
    backend = CassetteRecorder(CASSETTES, "record").wrap(real)
    policy = LLMPolicyConfig()
    client = LLMClient(backend, None, Budget(None, None), CallRecorder(), LLMPolicy(policy))
    judge = Judge(client, VM_JUDGE, PromptRegistry([PROMPT_ROOT]), nonce_key=CALIBRATION_NONCE)
    items = cassette_items(load_config(REPO / "experiments/rq2/configs/rq2_judges.yaml"))
    for item in items:
        verdict = asyncio.run(judge.score(make_task(item.metric, **item.inputs)))
        assert verdict.raw_score is not None
    assert len(list(CASSETTES.glob("*.json"))) >= len(items)
