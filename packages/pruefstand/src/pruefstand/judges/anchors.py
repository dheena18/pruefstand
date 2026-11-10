"""Drift anchors of a pinned judge (T5.4 S9, X3.4): ``judges/data/anchors/<model-slug>.jsonl``.

One line per anchor: the rendered judge request (messages exactly as sent, so the nightly re-judges
the identical prompt without the nonce key) and the judge's stored raw verdict.
"""

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from pruefstand.core.errors import ConfigError
from pruefstand.core.models.judge import JudgeVerdict
from pruefstand.core.models.llm import LLMRequest, LLMRole, Message
from pruefstand.judges.judge import JUDGE_MAX_TOKENS
from pruefstand.judges.output import normalise, output_schema, spec_of

ANCHOR_DIR = Path(__file__).resolve().parent / "data" / "anchors"
_MAX_BYTES = 5_000_000


class AnchorItem(BaseModel):
    """One stored anchor: where it comes from, the rendered request and the stored verdict."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    anchor_id: str
    item_id: str
    label_set: str
    metric: str
    label: int
    hard_negative: bool
    judge_model: str
    prompt_id: str
    prompt_version: str
    messages: tuple[Message, ...]
    raw_score: int

    def request(self) -> LLMRequest:
        """The judge request of this anchor (temperature 0, the metric's JSON schema)."""
        return LLMRequest(
            role=LLMRole.JUDGE,
            model=self.judge_model,
            messages=self.messages,
            temperature=0.0,
            max_tokens=JUDGE_MAX_TOKENS,
            prompt_id=self.prompt_id,
            prompt_version=self.prompt_version,
            response_format="json",
            json_schema=output_schema(self.metric),
        )

    def stored_verdict(self) -> JudgeVerdict:
        """The stored raw verdict as a ``JudgeVerdict`` (``reason`` is not stored)."""
        return verdict_of(self.metric, self.raw_score, self.judge_model)


def verdict_of(metric: str, raw: int, model: str) -> JudgeVerdict:
    """Build an uncached verdict from a raw score."""
    spec_of(metric)
    return JudgeVerdict(
        score=normalise(metric, raw), reason="", raw_score=raw, judge_model=model, cached=False
    )


def anchor_file(model: str, directory: Path = ANCHOR_DIR) -> Path:
    """Path of a judge's anchor file (``ollama/gemma3:12b`` -> ``ollama_gemma3-12b.jsonl``)."""
    return directory / f"{model.replace('/', '_').replace(':', '-')}.jsonl"


def load_anchors(path: Path) -> list[AnchorItem]:
    """Read an anchor file.

    Raises:
        ConfigError: The file is too large or a line is not a valid anchor.
    """
    raw = path.read_bytes()
    if len(raw) > _MAX_BYTES:
        msg = f"{path.name}: larger than {_MAX_BYTES} bytes"
        raise ConfigError(msg)
    try:
        return [
            AnchorItem.model_validate(json.loads(line))
            for line in raw.decode("utf-8").splitlines()
            if line.strip()
        ]
    except (ValueError, ValidationError) as err:
        msg = f"{path.name}: not a valid anchor file ({type(err).__name__})"
        raise ConfigError(msg) from err
