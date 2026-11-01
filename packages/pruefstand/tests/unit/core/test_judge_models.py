import pytest
from pydantic import ValidationError

from pruefstand.core.models.judge import JudgeTask, JudgeVerdict


def task() -> JudgeTask:
    return JudgeTask(
        metric="faithfulness",
        prompt_id="faithfulness_de",
        prompt_version="1",
        inputs={"frage": "Gilt die „Kündigung“ zum Monatsende?", "antwort": "Ja."},
    )


def verdict(**changes: object) -> JudgeVerdict:
    data: dict[str, object] = {
        "score": 0.5,
        "reason": "Teilweise belegt durch § 622 BGB („Kündigung“).",
        "raw_score": 1,
        "judge_model": "ollama/gemma3:12b",
        "cached": False,
    }
    return JudgeVerdict.model_validate({**data, **changes})


def test_task_json_round_trip_keeps_german_text() -> None:
    original = task()
    text = original.model_dump_json()
    assert "„Kündigung“" in text  # UTF-8 literal, not escaped
    assert JudgeTask.model_validate_json(text) == original


def test_verdict_json_round_trip_keeps_german_text() -> None:
    original = verdict()
    assert JudgeVerdict.model_validate_json(original.model_dump_json()) == original


def test_extra_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        JudgeTask.model_validate({**task().model_dump(), "extra": 1})
    with pytest.raises(ValidationError):
        verdict(extra=1)


def test_models_are_frozen() -> None:
    with pytest.raises(ValidationError):
        task().metric = "x"  # type: ignore[misc]  # frozen model: the assignment must fail
    with pytest.raises(ValidationError):
        verdict().score = 1.0  # type: ignore[misc]  # frozen model: the assignment must fail


def test_raw_score_is_a_strict_int() -> None:
    with pytest.raises(ValidationError):
        verdict(raw_score="2")
    with pytest.raises(ValidationError):
        verdict(raw_score=1.0)
