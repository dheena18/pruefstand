"""German smoke cases of the model benchmark (T3.1b S3): load, prompts, 0-2 scoring.

``questions_de.jsonl`` holds one case per line. The deterministic score is a proxy for the GitHub
Models and human scoring of S3: all checks met = 2, at least half = 1, else 0; empty answers,
``<think>`` blocks, a
forbidden pattern or an English answer score 0.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from model_selection.stats import json_valid

HERE = Path(__file__).resolve().parent
CASES_PATH = HERE / "questions_de.jsonl"
PROMPT_DIR = HERE / "prompts"
QA_KINDS = frozenset({"law_qa", "refusal", "umlaut"})
JUDGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"reason": {"type": "string", "maxLength": 600}, "score": {"type": "integer"}},
    "required": ["reason", "score"],
}
_DE = frozenset(
    [
        "der",
        "die",
        "das",
        "und",
        "ist",
        "nicht",
        "ein",
        "eine",
        "zu",
        "den",
        "mit",
        "von",
        "für",
        "auf",
        "im",
        "ich",
        "du",
        "dir",
        "es",
        "sich",
        "wird",
        "kann",
    ]
)
_EN = frozenset(
    ["the", "and", "is", "of", "to", "in", "that", "it", "for", "with", "are", "was", "this"]
)
_WORD = re.compile(r"[A-Za-zÄÖÜäöüß]+")
_SENTENCE_END = re.compile(r"[.!?](?:\s|$)")


@dataclass(frozen=True)
class Case:
    """One benchmark item.

    ``checks`` may hold ``must``, ``must_any``, ``forbid``, ``max_sentences``, ``json``.
    """

    id: str
    kind: str
    question: str
    context: str = ""
    ref: str = ""
    checks: dict[str, Any] = field(default_factory=dict)

    @property
    def prompt(self) -> str:
        """The user message: optional context block, then the question."""
        return (f"Kontext:\n{self.context}\n\n" if self.context else "") + self.question


def load_cases(path: Path = CASES_PATH) -> list[Case]:
    """Read the JSONL file (UTF-8, one object per line)."""
    rows = (json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip())
    return [Case(**row) for row in rows]


def prompt_text(name: str) -> str:
    """Return a versioned prompt file of ``prompts/`` (e.g. ``qa_system_v1``)."""
    return (PROMPT_DIR / f"{name}.txt").read_text(encoding="utf-8").strip()


def build_messages(case: Case) -> list[dict[str, str]]:
    """Chat messages for ``case``.

    The QA system prompt for context-bound kinds, else the user message only.
    """
    msgs = [{"role": "user", "content": case.prompt}]
    if case.kind in QA_KINDS:
        msgs.insert(0, {"role": "system", "content": prompt_text("qa_system_v1")})
    return msgs


def judge_messages(context: str, question: str, answer: str) -> list[dict[str, str]]:
    """Faithfulness judge prompt (``judge_v1``) filled with context, question and answer."""
    body = prompt_text("judge_v1").format(context=context, question=question, answer=answer)
    return [{"role": "user", "content": body}]


def is_german(text: str) -> bool:
    """False when the text has at least two English stop words and more of them than German ones."""
    words = [w.lower() for w in _WORD.findall(text)]
    de, en = sum(w in _DE for w in words), sum(w in _EN for w in words)
    return not (en >= 2 and en > de)


def _passed(case: Case, answer: str) -> list[bool]:
    ck, flags = case.checks, re.IGNORECASE
    res = [bool(re.search(p, answer, flags)) for p in ck.get("must", [])]
    if ck.get("must_any"):
        res.append(any(re.search(p, answer, flags) for p in ck["must_any"]))
    if "max_sentences" in ck:
        res.append(len(_SENTENCE_END.findall(answer)) <= ck["max_sentences"])
    if ck.get("json"):
        res.append(
            json_valid(answer)
            and ("expect_score" not in ck or json.loads(answer)["score"] == ck["expect_score"])
        )
    return res


def score_case(case: Case, answer: str) -> int:
    """Deterministic 0-2 score of ``answer`` for ``case``."""
    if not answer.strip() or "<think>" in answer or not is_german(answer):
        return 0
    if any(re.search(p, answer) for p in case.checks.get("forbid", [])):
        return 0
    res = _passed(case, answer)
    share = sum(res) / len(res) if res else 1.0
    return 2 if share == 1.0 else 1 if share >= 0.5 else 0
