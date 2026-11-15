"""Per-item regeneration of the in-domain dev set (D1201) on two REAL answers for § 9 EntgFG.

``fixtures/indomain_retry_entgfg9.json`` holds the passage (official text, public domain) and the
real replies of the two VM models from the D1200 benchmark: the 8B reply quotes an evidence span
over 400 characters (invalid), the 14B reply is valid. The cache is a temporary directory.
"""

import json
from pathlib import Path

import pytest
from model_selection import indomain_data as data
from model_selection import indomain_gen as gen
from model_selection import indomain_retry as retry

FIXTURE = Path(__file__).parent / "fixtures" / "indomain_retry_entgfg9.json"
DOC = json.loads(FIXTURE.read_text(encoding="utf-8"))
PASSAGE = data.Passage(**DOC["passage"])
INVALID = DOC["replies"]["ministral-3-8b-instruct-2512"]
VALID = DOC["replies"]["ministral-3-14b-instruct-2512"]
MODEL = "openai_compatible_local/ministral-3-14b-instruct-2512"


@pytest.fixture(autouse=True)
def _cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(gen, "CACHE", tmp_path)


def _store(key: str, text: str) -> None:
    gen.CACHE.mkdir(parents=True, exist_ok=True)
    rec = {"model": MODEL, "prompt": data.GEN_PROMPT, "passage_id": key, "response": text}
    gen.cache_path(MODEL, data.GEN_PROMPT, key).write_text(json.dumps(rec), encoding="utf-8")


def _run(replies: list[str], *, retries: int, max_calls: int) -> tuple[retry.Tally, list[str]]:
    keys: list[str] = []

    def call(key: str, _p: data.Passage) -> None:
        keys.append(key)
        _store(key, replies[len(keys) - 1])

    tally = retry.run_generate(
        [PASSAGE],
        lambda pid: retry.answers(MODEL, pid, retries),
        call,
        retries=retries,
        max_calls=max_calls,
        tally=retry.Tally(),
    )
    return tally, keys


def test_the_two_real_answers_are_judged_as_recorded() -> None:
    assert retry.judge_answer(INVALID, PASSAGE.text) == (None, "span_length")
    item, reason = retry.judge_answer(VALID, PASSAGE.text)
    assert item is not None
    assert reason == ""


def test_an_invalid_first_answer_is_asked_again_and_the_valid_one_is_used() -> None:
    tally, keys = _run([INVALID, VALID], retries=2, max_calls=10)
    assert keys == ["gii-entgfg-9", "gii-entgfg-9#retry1"]
    assert (tally.calls, tally.retries, tally.exhausted) == (2, 1, 0)
    item, _ = retry.first_valid(retry.answers(MODEL, PASSAGE.id, 2), PASSAGE.text)
    assert item is not None
    assert item["evidence_span"] in PASSAGE.text


def test_regeneration_stops_after_n_retries_and_counts_every_call() -> None:
    tally, keys = _run([INVALID] * 5, retries=2, max_calls=10)
    assert keys == ["gii-entgfg-9", "gii-entgfg-9#retry1", "gii-entgfg-9#retry2"]
    assert (tally.calls, tally.retries, tally.exhausted) == (3, 2, 1)
    assert retry.first_valid(retry.answers(MODEL, PASSAGE.id, 2), PASSAGE.text) == (
        None,
        "span_length",
    )


def test_the_call_budget_stops_a_retry_and_a_rerun_continues_there() -> None:
    tally, keys = _run([INVALID], retries=2, max_calls=1)
    assert (tally.calls, keys) == (1, ["gii-entgfg-9"])
    tally, keys = _run([VALID], retries=2, max_calls=5)
    assert keys == ["gii-entgfg-9#retry1"]
    assert (tally.calls, tally.retries) == (1, 1)


def test_zero_retries_keeps_the_old_one_call_rule() -> None:
    tally, keys = _run([INVALID, VALID], retries=0, max_calls=10)
    assert keys == ["gii-entgfg-9"]
    assert tally.exhausted == 1


def test_a_valid_cached_answer_makes_no_call() -> None:
    _store("gii-entgfg-9", VALID)
    tally, keys = _run([], retries=2, max_calls=10)
    assert keys == []
    assert tally.calls == 0


def test_the_generation_schema_matches_the_validation_limits() -> None:
    span = gen.GEN_SCHEMA["properties"]["evidence_span"]
    assert (span["minLength"], span["maxLength"]) == (20, 400)
    assert set(gen.GEN_SCHEMA["required"]) == {"question", "evidence_span", "reference_answer"}
