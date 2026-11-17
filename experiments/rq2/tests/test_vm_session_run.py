"""T5.4e session runner: the planned calls match run_judges (resume = the judge cache)."""

import argparse

import pytest
from rq2.vm_session_run import _inputs, planned_tasks

SETS = ["faithfulness_constructed", "correctness", "refusal", "consistency"]


def test_the_plan_is_run_judges_selection_in_order() -> None:
    args = argparse.Namespace(sets=SETS, limit=2, pairs=False)
    tasks = planned_tasks(args)
    assert len(tasks) == 2 * len(SETS)
    assert tasks == planned_tasks(args)  # same order every session: the cache keys repeat


def test_pair_inputs_must_be_objects() -> None:
    assert _inputs({"answer": "Ja.", "n": 1}) == {"answer": "Ja.", "n": "1"}
    with pytest.raises(TypeError, match="object"):
        _inputs(["not", "an", "object"])
