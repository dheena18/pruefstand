"""Judge output model, scales and the schema sent as Ollama ``format`` (S1, AI11-14e)."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from testsupport.judge_support import MODEL, TAGS, configure, make_judge
from testsupport.loopback_script import Step, ollama_body, serve_script

from pruefstand.core.errors import ConfigError, LLMError
from pruefstand.judges.output import (
    REASON_MAX,
    SPECS,
    JudgeOutput,
    make_task,
    normalise,
    output_model,
    output_schema,
)

FILLER = {"frage": "F?", "kontext": "K", "antwort": "A", "referenz": "R"}


def test_the_schema_puts_reason_before_score_and_bounds_the_reason() -> None:
    schema = output_schema("faithfulness")
    props = _props(schema)
    assert list(props) == ["reason", "score"]
    assert props["reason"]["maxLength"] == REASON_MAX == 600
    assert props["score"]["maximum"] == 2
    assert schema["additionalProperties"] is False


def test_the_binary_scale_has_maximum_one() -> None:
    assert _props(output_schema("refusal_judged"))["score"]["maximum"] == 1


@pytest.mark.parametrize(
    ("metric", "raw", "expected"),
    [
        ("faithfulness", 2, 1.0),
        ("faithfulness", 1, 0.5),
        ("faithfulness", 0, 0.0),
        ("answer_correctness", 1, 0.5),
        ("perturbation_consistency", 1, 1.0),
        ("refusal_judged", 0, 0.0),
    ],
)
def test_normalisation_follows_the_scales(metric: str, raw: int, expected: float) -> None:
    assert normalise(metric, raw) == expected


def test_an_unknown_metric_is_a_config_error() -> None:
    with pytest.raises(ConfigError, match="nope"):
        normalise("nope", 1)
    with pytest.raises(ConfigError, match="nope"):
        output_model("nope")


@pytest.mark.parametrize(
    "text",
    [
        '{"reason": "x", "score": "2"}',
        '{"reason": "x", "score": 1.5}',
        '{"reason": "", "score": 1}',
        '{"reason": "x", "score": 3}',
        '{"reason": "x", "score": -1}',
        '{"reason": "x", "score": 1, "extra": 1}',
        '{"score": 1}',
    ],
)
def test_invalid_outputs_are_rejected(text: str) -> None:
    with pytest.raises(ValidationError):
        output_model("faithfulness").model_validate_json(text)


def test_the_reason_may_not_exceed_the_bound() -> None:
    long = json.dumps({"reason": "x" * (REASON_MAX + 1), "score": 1})
    with pytest.raises(ValidationError):
        JudgeOutput.model_validate_json(long)
    ok = json.dumps({"reason": "x" * REASON_MAX, "score": 1})
    assert JudgeOutput.model_validate_json(ok).score == 1


def test_the_binary_range_refuses_two() -> None:
    with pytest.raises(ValidationError):
        output_model("refusal_judged").model_validate_json('{"reason": "x", "score": 2}')


def test_every_metric_has_a_spec_with_its_prompt_variables() -> None:
    assert set(SPECS) == {
        "faithfulness",
        "answer_correctness",
        "perturbation_consistency",
        "refusal_judged",
    }
    task = make_task("refusal_judged", frage="F?", antwort="A")
    assert (task.prompt_id, task.prompt_version) == ("refusal_judged_de", "v1")
    assert (
        make_task("faithfulness", **_vars("faithfulness")).prompt_version
        == SPECS["faithfulness"].version
    )
    with pytest.raises(ConfigError, match="erwartet"):
        make_task("refusal_judged", frage="F?", antwort="A", erwartet="E")


async def test_raw_three_on_the_faithfulness_scale_is_an_llm_error_after_repair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bad = Step(body=_ollama('{"reason": "zu hoch", "score": 3}'))
    with serve_script([bad, bad], tags=TAGS) as (origin, state):
        configure(tmp_path, monkeypatch, origin)
        judge, _ = make_judge()
        with pytest.raises(LLMError, match="invalid JSON after one repair"):
            await judge.score(make_task("faithfulness", **_vars("faithfulness")))
    assert state.posts() == 2  # the call and one repair, nothing more


async def test_the_schema_is_sent_as_the_native_format(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    good = Step(body=_ollama('{"reason": "belegt", "score": 2}'))
    with serve_script([good], tags=TAGS) as (origin, state):
        configure(tmp_path, monkeypatch, origin)
        judge, _ = make_judge()
        await judge.score(make_task("faithfulness", **_vars("faithfulness")))
    (post,) = [s for s in state.seen if s.method == "POST" and s.path == "/api/chat"]
    props = _props(post.body["format"])
    assert list(props) == ["reason", "score"]
    assert props["reason"]["maxLength"] == 600
    assert post.body["model"] == MODEL.removeprefix("ollama/")


def _vars(metric: str) -> dict[str, str]:
    return {name: FILLER[name] for name in SPECS[metric].variables}


def _ollama(text: str) -> bytes:
    return ollama_body(text)


def _props(schema: object) -> dict[str, dict[str, object]]:
    assert isinstance(schema, dict)
    props = schema["properties"]
    assert isinstance(props, dict)
    return props
