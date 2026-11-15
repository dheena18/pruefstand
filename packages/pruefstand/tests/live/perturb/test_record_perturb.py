"""Recording scenario for `make cassettes` (T4.5): REAL rewrites and equivalence checks.

Needs the pinned rewrite model (``PRUEFSTAND_PERTURB_REWRITE_MODEL``: the VM CPU model
``openai_compatible_local/ministral-3-14b-instruct-2512`` at ``PRUEFSTAND_DATAGEN_BASE_URL``, D1201,
or a ``github/`` id plus ``PRUEFSTAND_GH_MODELS_TOKEN``), the A40 judge in day mode under
``pruefstand-lock``
(``PRUEFSTAND_PERTURB_JUDGE_MODEL`` + endpoint env) and ``--record-mode=rewrite``.
Skipped otherwise.
Never hand-write the result: the cassettes are the answers of those models.
"""

import json
import os
from datetime import UTC, datetime

import numpy as np
import pytest
from testsupport.perturb_pilot import CASSETTES, RECORDED, build, env_meta, questions

from pruefstand.core.config import LLMPolicyConfig, ModelRef
from pruefstand.core.settings import PruefstandSettings
from pruefstand.dataset.vm_datagen import VM_PROVIDER, build_vm_backend
from pruefstand.llm.cassettes import CassetteRecorder
from pruefstand.llm.factory import build_backend
from pruefstand.llm.families import family_of
from pruefstand.llm.policy import provider_of

pytestmark = [pytest.mark.live, pytest.mark.gpu, pytest.mark.network]


@pytest.fixture(autouse=True)
def _only_when_recording(request: pytest.FixtureRequest) -> None:
    if request.config.getoption("--record-mode", default=None) != "rewrite":
        pytest.skip("recording runs only with --record-mode=rewrite (make cassettes)")
    meta = env_meta()
    if meta is None:
        pytest.skip("needs the PRUEFSTAND_PERTURB_{REWRITE,JUDGE}_MODEL variables")
    github = meta.rewrite_model.startswith("github/")
    if github and not os.environ.get("PRUEFSTAND_GH_MODELS_TOKEN"):
        pytest.skip("a github/ rewrite model needs PRUEFSTAND_GH_MODELS_TOKEN")


async def test_record_rewrites_and_equivalence_checks() -> None:
    meta = env_meta()
    assert meta is not None
    policy = LLMPolicyConfig()
    rewrite_ref = ModelRef(id=meta.rewrite_model, family=family_of(meta.rewrite_model))
    rewrite = (
        build_vm_backend(rewrite_ref, PruefstandSettings().datagen_base_url)
        if provider_of(meta.rewrite_model) == VM_PROVIDER
        else build_backend(rewrite_ref, policy=policy)
    )
    judge = build_backend(
        ModelRef(id=meta.judge_model, family=family_of(meta.judge_model)), policy=policy
    )
    CASSETTES.mkdir(parents=True, exist_ok=True)
    (CASSETTES / "rewrite").mkdir(exist_ok=True)
    (CASSETTES / "validate").mkdir(exist_ok=True)
    perturbations, client = build(
        meta,
        CassetteRecorder(CASSETTES / "rewrite", "record").wrap(rewrite),
        CassetteRecorder(CASSETTES / "validate", "record").wrap(judge),
    )
    for question in questions()[:RECORDED]:
        for p in perturbations:
            await p.aapply(question, client, np.random.default_rng(0))
    stamp = {**meta.model_dump(), "recorded_at": datetime.now(UTC).isoformat(timespec="seconds")}
    (CASSETTES / "meta.json").write_text(json.dumps(stamp, indent=2) + "\n", encoding="utf-8")
