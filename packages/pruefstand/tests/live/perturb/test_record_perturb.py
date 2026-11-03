"""Recording scenario for `make cassettes` (T4.5): REAL rewrites and equivalence checks.

Needs ``PRUEFSTAND_GH_MODELS_TOKEN`` (Models: read), the pinned rewrite model
(``PRUEFSTAND_PERTURB_REWRITE_MODEL``), the A40 judge in day mode under ``pruefstand-lock``
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
from pruefstand.llm.cassettes import CassetteRecorder
from pruefstand.llm.factory import build_backend
from pruefstand.llm.families import family_of

pytestmark = [pytest.mark.live, pytest.mark.gpu, pytest.mark.network]


@pytest.fixture(autouse=True)
def _only_when_recording(request: pytest.FixtureRequest) -> None:
    if request.config.getoption("--record-mode", default=None) != "rewrite":
        pytest.skip("recording runs only with --record-mode=rewrite (make cassettes)")
    if not os.environ.get("PRUEFSTAND_GH_MODELS_TOKEN") or env_meta() is None:
        pytest.skip("needs PRUEFSTAND_GH_MODELS_TOKEN and the PRUEFSTAND_PERTURB_*_MODEL variables")


async def test_record_rewrites_and_equivalence_checks() -> None:
    meta = env_meta()
    assert meta is not None
    policy = LLMPolicyConfig()
    rewrite = build_backend(
        ModelRef(id=meta.rewrite_model, family=family_of(meta.rewrite_model)), policy=policy
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
