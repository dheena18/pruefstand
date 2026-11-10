"""The prompts of the ``prompt_budget`` calibration (T3.6b, D960): shared by recorder and replay.

``CASES`` are built from the committed corpus slice only, so the recorded Ollama numbers can be
checked against the very same prompts later (``messages_sha256`` pins them).
"""

import hashlib
import json
from pathlib import Path
from typing import NamedTuple

from rd_support import CONFIGS, REPO, hit, slice_chunks

from rag_demo.config import load_config
from rag_demo.generation import build_prompt
from rag_demo.models import RagConfig

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "budget_calibration.json"
Q_NOTICE = "Welche Kündigungsfrist gilt nach zwei Jahren Betriebszugehörigkeit?"
Q_SICK = "Wann darf der Arbeitgeber mir kündigen, wenn ich krank bin?"


class Case(NamedTuple):
    """One calibration prompt: a question over the first ``hits`` chunks of the slice."""

    name: str
    question: str
    hits: int


CASES = [
    Case("one_hit", Q_NOTICE, 1),
    Case("three_hits", Q_SICK, 3),
    Case("five_hits", Q_NOTICE, 5),
    Case("between_budget_and_num_ctx", Q_NOTICE, 45),
    Case("over_num_ctx", Q_NOTICE, 60),
]


def gpu_config() -> RagConfig:
    """The tier-2 config checked against the catalogue (the one that sets ``num_ctx``)."""
    return load_config(CONFIGS / "rag.gpu.yaml", REPO / "infra" / "gpu" / "models.yaml")


def case_messages(case: Case, cfg: RagConfig) -> list[dict[str, str]]:
    """The chat messages ``/v1/query`` would send for ``case`` (no budget cut)."""
    ids = [str(c["chunk_id"]) for c in slice_chunks()][: case.hits]
    return build_prompt(case.question, [hit(c, r) for r, c in enumerate(ids, 1)], cfg)


def messages_sha256(messages: list[dict[str, str]]) -> str:
    """Hash of the messages; a changed prompt file or slice makes the recorded numbers stale."""
    blob = json.dumps(messages, ensure_ascii=False, sort_keys=True).encode()
    return hashlib.sha256(blob).hexdigest()
