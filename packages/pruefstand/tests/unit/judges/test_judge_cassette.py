"""Replay of recorded real judge answers (cassettes from ``record_cassettes.sh --judges``)."""

import pytest
from testsupport.judge_cassettes import CASSETTES, TASKS, judge_id, judge_with

from pruefstand.core.models.judge import JudgeTask
from pruefstand.judges.output import spec_of

pytestmark = pytest.mark.skipif(
    not any(CASSETTES.glob("*.json")),
    reason="no judge cassettes yet: record them with scripts/models/record_cassettes.sh --judges",
)


@pytest.mark.parametrize("task", TASKS, ids=lambda t: f"{t.metric}")
async def test_a_recorded_real_answer_parses_into_a_verdict(task: JudgeTask) -> None:
    verdict = await judge_with("replay", None).score(task)
    assert 0 <= verdict.raw_score <= spec_of(task.metric).max_raw
    assert verdict.score == verdict.raw_score / spec_of(task.metric).max_raw
    assert verdict.judge_model == judge_id()
    assert verdict.reason
