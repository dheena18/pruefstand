"""Judge task and verdict models (interfaces §6); implemented by ``judges`` in T5.2a."""

from pydantic import BaseModel, ConfigDict, StrictInt


class JudgeTask(BaseModel):
    """One judging request: which metric, which versioned prompt, which labelled inputs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    metric: str
    prompt_id: str
    prompt_version: str
    inputs: dict[str, str]


class JudgeVerdict(BaseModel):
    """A judge's answer.

    Scales (SPEC §7.3): ``faithfulness`` and ``answer_correctness`` use raw 0/1/2, scored
    0 / 0.5 / 1; ``perturbation_consistency`` and ``refusal_judged`` use raw 0/1, scored 0 / 1.

    Raises:
        ValidationError: ``raw_score`` is not an ``int`` (strings such as ``"2"`` and floats are
            refused), or an unknown field is given.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    score: float
    reason: str
    raw_score: StrictInt
    judge_model: str
    cached: bool
