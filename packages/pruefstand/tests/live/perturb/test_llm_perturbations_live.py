"""Real models, 5 questions x 4 perturbations (T4.5): needs GitHub Models and the A40 judge.

Every accepted output differs from its input, passes ``static_check`` and keeps all numbers and
paragraph references; the compound split of "Kündigungsschutzgesetz" keeps "Kündigung" and "Schutz".
"""

import os

import numpy as np
import pytest
from testsupport.perturb_pilot import build, env_meta, questions

from pruefstand.core.config import LLMPolicyConfig, ModelRef
from pruefstand.llm.factory import build_backend
from pruefstand.llm.families import family_of
from pruefstand.perturb.draft import Draft
from pruefstand.perturb.validate import static_check

pytestmark = [pytest.mark.live, pytest.mark.gpu, pytest.mark.network]


@pytest.fixture(autouse=True)
def _needs_models() -> None:
    if not os.environ.get("PRUEFSTAND_GH_MODELS_TOKEN") or env_meta() is None:
        pytest.skip("needs PRUEFSTAND_GH_MODELS_TOKEN and the PRUEFSTAND_PERTURB_*_MODEL variables")


async def test_accepted_outputs_are_valid_and_keep_numbers() -> None:
    meta = env_meta()
    assert meta is not None
    policy = LLMPolicyConfig()
    backends = [
        build_backend(ModelRef(id=m, family=family_of(m)), policy=policy)
        for m in (meta.rewrite_model, meta.judge_model)
    ]
    perturbations, client = build(meta, backends[0], backends[1])
    seen_compound = False
    for question in questions()[:5]:
        for p in perturbations:
            res = await p.aapply(question, client, np.random.default_rng(0))
            if not res.changed:
                continue
            assert res.text != question
            assert static_check(p.name, question, Draft(text=res.text, variant=res.notes)) in (
                None,
                "transformation_missing",  # variant/targets are not known here
            )
            if p.name == "compound_split" and "Kündigungsschutzgesetz" in question:
                seen_compound = True
                assert "Kündigung" in res.text
                assert "Schutz" in res.text
    assert seen_compound
