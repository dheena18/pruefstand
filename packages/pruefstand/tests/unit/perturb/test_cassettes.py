"""Replay of the cassettes recorded from the REAL pinned models (T4.5, `make cassettes`).

Skipped until the lead / owner has recorded them ([NET][GPU]); cassettes are never hand-written.
"""

import numpy as np
import pytest
from testsupport.perturb_pilot import CASSETTES, RECORDED, build, load_meta, questions

from pruefstand.llm.cassettes import CassetteRecorder
from pruefstand.perturb.draft import Draft
from pruefstand.perturb.validate import static_check

META = load_meta()
pytestmark = pytest.mark.skipif(
    META is None, reason="tests/cassettes/perturb not recorded yet (make cassettes, [NET][GPU])"
)


async def test_recorded_exchanges_replay_to_valid_outputs() -> None:
    assert META is not None
    perturbations, client = build(
        META,
        CassetteRecorder(CASSETTES / "rewrite", "replay").wrap(None),
        CassetteRecorder(CASSETTES / "validate", "replay").wrap(None),
    )
    accepted = 0
    for question in questions()[:RECORDED]:
        for p in perturbations:
            res = await p.aapply(question, client, np.random.default_rng(0))
            if res.changed:
                accepted += 1
                assert res.text != question
                assert static_check(p.name, question, Draft(text=res.text)) in (
                    None,
                    "transformation_missing",
                )
    assert accepted > 0


async def test_compound_split_of_kuendigungsschutzgesetz() -> None:
    assert META is not None
    perturbations, client = build(
        META,
        CassetteRecorder(CASSETTES / "rewrite", "replay").wrap(None),
        CassetteRecorder(CASSETTES / "validate", "replay").wrap(None),
    )
    split = next(p for p in perturbations if p.name == "compound_split")
    res = await split.aapply(questions()[0], client, np.random.default_rng(0))
    assert res.changed
    assert "Kündigung" in res.text
    assert "Schutz" in res.text
