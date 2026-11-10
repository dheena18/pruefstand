"""Judge output: the JSON the judge returns, the four scales and the metric -> prompt table."""

from dataclasses import dataclass
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from pruefstand.core.errors import ConfigError
from pruefstand.core.models.judge import JudgeTask

REASON_MAX = 600  # characters; bounds the grammar-constrained output (round 11 AI11-14e)


class JudgeOutput(BaseModel):
    """The answer of a judge: the reason first, so the model reasons before it scores.

    Raises:
        ValidationError: ``reason`` is empty or longer than 600 characters, ``score`` is not an
            ``int`` (``"2"`` and ``1.5`` are refused), or an unknown field is present.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    reason: str = Field(min_length=1, max_length=REASON_MAX)
    score: StrictInt


class ThreePointOutput(JudgeOutput):
    """Raw scale 0 / 1 / 2 (faithfulness, answer_correctness)."""

    score: Annotated[StrictInt, Field(ge=0, le=2)]


class BinaryOutput(JudgeOutput):
    """Raw scale 0 / 1 (perturbation_consistency, refusal_judged)."""

    score: Annotated[StrictInt, Field(ge=0, le=1)]


@dataclass(frozen=True)
class MetricSpec:
    """Scale and prompt of one judged metric.

    Attributes:
        max_raw: Highest raw score; the normalised score is ``raw / max_raw``.
        prompt_id: Prompt file stem without the version (``<metric>_de``).
        variables: The prompt variables, which are the labelled input blocks.
        version: The prompt version ``make_task`` asks for (older files stay on disk, immutable).
    """

    max_raw: int
    prompt_id: str
    variables: tuple[str, ...]
    version: str = "v1"


SPECS: dict[str, MetricSpec] = {
    "faithfulness": MetricSpec(2, "faithfulness_de", ("frage", "kontext", "antwort"), "v2"),
    "answer_correctness": MetricSpec(
        2, "answer_correctness_de", ("frage", "referenz", "antwort"), "v4"
    ),
    "perturbation_consistency": MetricSpec(
        1, "perturbation_consistency_de", ("frage", "referenz", "antwort")
    ),
    "refusal_judged": MetricSpec(1, "refusal_judged_de", ("frage", "antwort")),
}


def spec_of(metric: str) -> MetricSpec:
    """Return the spec of ``metric``.

    Raises:
        ConfigError: ``metric`` is not a judged metric (named).
    """
    if metric not in SPECS:
        msg = f"'{metric}' is not a judged metric (known: {', '.join(sorted(SPECS))})"
        raise ConfigError(msg)
    return SPECS[metric]


def output_model(metric: str) -> type[JudgeOutput]:
    """Return the validating output model of ``metric`` (range 0..2 or 0..1).

    Raises:
        ConfigError: Unknown metric.
    """
    return ThreePointOutput if spec_of(metric).max_raw == 2 else BinaryOutput


def output_schema(metric: str) -> dict[str, object]:
    """Return the JSON Schema sent as the Ollama ``format`` (``reason`` before ``score``).

    Examples:
        >>> list(output_schema("refusal_judged")["properties"])
        ['reason', 'score']
    """
    return output_model(metric).model_json_schema()


def normalise(metric: str, raw: int) -> float:
    """Return the normalised score of a raw one: ``raw / max_raw``.

    Examples:
        >>> normalise("faithfulness", 1), normalise("refusal_judged", 1)
        (0.5, 1.0)

    Raises:
        ConfigError: Unknown metric.
    """
    return raw / spec_of(metric).max_raw


def make_task(metric: str, **inputs: str) -> JudgeTask:
    """Build the ``JudgeTask`` of ``metric`` with the current prompt version of its spec.

    Args:
        metric: A judged metric.
        **inputs: One text per prompt variable (``frage``, ``antwort``, ...).

    Raises:
        ConfigError: Unknown metric, or the inputs are not exactly the prompt's variables (the
            refusal prompt, for example, never takes ``erwartet``).
    """
    spec = spec_of(metric)
    if set(inputs) != set(spec.variables):
        msg = f"{metric}: inputs {sorted(inputs)} must be exactly {sorted(spec.variables)}"
        raise ConfigError(msg)
    return JudgeTask(
        metric=metric, prompt_id=spec.prompt_id, prompt_version=spec.version, inputs=inputs
    )
