"""Owner-scored items (D855): the deterministic scorer against the owner-reviewed scores."""

import json
from pathlib import Path

from model_selection import bench_cases as bc
from model_selection.owner_sheet import GENERATOR_ID

ANSWERS = Path(__file__).resolve().parents[1] / "results" / "2026-11-03_answers.jsonl"


def _answer(case_id: str) -> str:
    rows = (json.loads(x) for x in ANSWERS.read_text(encoding="utf-8").splitlines())
    return str(
        next(r["answer"] for r in rows if r["model"] == GENERATOR_ID and r["case"] == case_id)
    )


def _case(case_id: str) -> bc.Case:
    return next(c for c in bc.load_cases() if c.id == case_id)


def test_declined_bgb_expansion_is_found() -> None:
    """ge02: 'für das Bürgerliche Gesetzbuch' (declined) is a correct answer, not a miss."""
    case = _case("ge02")
    for text in (
        "BGB steht für das Bürgerliche Gesetzbuch.",
        "BGB ist das Bürgerliche Gesetzbuch.",
        "BGB: Bürgerliches Gesetzbuch.",
    ):
        assert bc.score_case(case, text) == 2
    assert bc.score_case(case, "BGB steht für Bundesgesetzbuch.") <= 1
    assert bc.score_case(case, _answer("ge02")) == 2  # owner score 2


def test_summary_of_the_limitation_period_must_name_a_condition() -> None:
    """su06: an answer that omits the conditions of section 199 (owner score 1) is not a 2."""
    case = _case("su06")
    assert bc.score_case(case, _answer("su06")) == 1
    full = (
        "Die Frist beginnt am Ende des Jahres, in dem der Anspruch entstanden ist. "
        "Man muss den Schuldner kennen oder es hätte wissen müssen."
    )
    assert bc.score_case(case, full) == 2


def test_known_limits_of_the_keyword_proxy_are_pinned() -> None:
    """rg04 and ge04 stay different from the owner review: a keyword scorer cannot see them.

    rg04 (owner 1): the only check is the register ('du'), so a miss scores 0, and truncation and
    factual errors are invisible. ge04 (owner 1): the expansion is right, the flaw is extra detail
    ('entered into force' on 25 May 2018). Changing these numbers must be a conscious decision.
    """
    assert bc.score_case(_case("rg04"), _answer("rg04")) == 0
    assert bc.score_case(_case("ge04"), _answer("ge04")) == 2
