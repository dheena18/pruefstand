from pathlib import Path

import pytest
from testsupport.judged_support import failing, judges, response, user_prompts, verdict
from testsupport.run_builders import make_case

from pruefstand.core.errors import LLMError
from pruefstand.core.models.metric import MetricStatus
from pruefstand.llm import retry
from pruefstand.metrics.judged.refusal import RefusalJudged
from pruefstand.metrics.judged.routing import is_ambiguous

TWELVE = "Das hängt vom Einzelfall ab und sollte geprüft werden, bevor man handelt."


async def test_a_phrase_match_decides_without_a_judge_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with judges(tmp_path, monkeypatch, []) as (pool, state, _):
        value = await RefusalJudged(judge_enabled=True).acompute(
            make_case(0), response("Die Dokumente enthalten dazu keine Information."), pool
        )
    # a clear refusal is the phrase list's business: this metric cannot reward it (SPEC 7.1)
    assert (value.status, value.value) == (MetricStatus.NOT_APPLICABLE, None)
    assert value.details["reason"] == "not_ambiguous"
    assert user_prompts(state) == []


async def test_the_flag_is_ignored_and_a_disagreement_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with judges(tmp_path, monkeypatch, []) as (pool, _, _):
        value = await RefusalJudged(judge_enabled=True).acompute(
            make_case(0),
            response("Die Dokumente enthalten dazu keine Information.", refused=False),
            pool,
        )
    assert value.value is None  # the phrase list decides elsewhere, the flag only informs
    assert value.details["refusal_flag_mismatch"] is True


async def test_a_short_answer_without_citation_or_number_is_judged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert len(TWELVE.split()) == 12
    with judges(tmp_path, monkeypatch, [verdict(1)]) as (pool, state, _):
        value = await RefusalJudged(judge_enabled=True).acompute(
            make_case(0, expect_refusal=True), response(TWELVE), pool
        )
    (prompt,) = user_prompts(state)
    assert (value.value, value.details["refused_source"]) == (1.0, "judge")
    assert "erwartet" not in prompt.lower()  # the judge is never told what was expected
    assert "expect" not in prompt.lower()


async def test_a_short_answer_with_a_paragraph_citation_is_not_judged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with judges(tmp_path, monkeypatch, []) as (pool, state, _):
        value = await RefusalJudged(judge_enabled=True).acompute(
            make_case(0), response("Das regelt § 622 BGB für alle Arbeitgeber."), pool
        )
    assert (value.value, value.details["reason"]) == (None, "not_ambiguous")
    assert user_prompts(state) == []


async def test_a_long_answer_with_a_hedge_is_judged_and_a_clear_one_is_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hedge = ("Die Kündigung kann erfolgen. " * 30) + "Die Dauer lässt sich nicht bestimmen."
    clear = "Die Kündigung kann erfolgen. " * 45
    assert len(hedge.split()) > 100
    with judges(tmp_path, monkeypatch, [verdict(0)]) as (pool, state, _):
        metric = RefusalJudged(judge_enabled=True)
        judged = await metric.acompute(make_case(0), response(hedge), pool)
        plain = await metric.acompute(make_case(0), response(clear), pool)
    assert judged.details["refused_source"] == "judge"
    assert (plain.status, plain.details["reason"]) == (MetricStatus.NOT_APPLICABLE, "not_ambiguous")
    assert len(user_prompts(state)) == 1


async def test_with_the_refusal_judge_not_passing_only_the_phrase_list_decides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with judges(tmp_path, monkeypatch, []) as (pool, state, _):
        value = await RefusalJudged(judge_enabled=False).acompute(
            make_case(0), response(TWELVE), pool
        )
    assert (value.value, value.details["reason"]) == (None, "refusal_judge_off")
    assert user_prompts(state) == []


async def test_a_judge_failure_raises_llm_error_for_the_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def no_wait(_: float) -> None:
        return None

    monkeypatch.setattr(retry, "pause", no_wait)
    with (
        judges(tmp_path, monkeypatch, [failing(503)] * 8) as (pool, _, _),
        pytest.raises(LLMError),
    ):
        await RefusalJudged(judge_enabled=True).acompute(make_case(0), response(TWELVE), pool)


def test_without_the_calibration_file_the_refusal_judge_is_off() -> None:
    assert RefusalJudged()._enabled is False  # judges/data/calibration_status.yaml is T5.4's


def test_ambiguity_rule() -> None:
    assert is_ambiguous(response("Das lässt sich nicht eindeutig sagen."))
    assert is_ambiguous(response(TWELVE))
    assert not is_ambiguous(response("Die Frist beträgt 4 Wochen."))
    assert not is_ambiguous(response("Dazu liegen keine Informationen vor."))  # phrase list


async def test_a_candidate_that_falsely_refuses_cannot_look_better_on_this_metric(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    refusing = response("Die Dokumente enthalten dazu keine Information.")
    with judges(tmp_path, monkeypatch, []) as (pool, _, _):
        value = await RefusalJudged(judge_enabled=True).acompute(make_case(0), refusing, pool)
    assert value.status is MetricStatus.NOT_APPLICABLE  # never a 1.0 for a phrase refusal
