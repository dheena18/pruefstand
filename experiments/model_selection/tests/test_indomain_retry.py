"""Per-item regeneration of the in-domain dev set (D1201) on REAL exchanges of ONE model.

``fixtures/indomain_retry_14b.json`` was written by ``model_selection.record_retry`` against the
running VM model (Ministral 3 14B, llama-server; request bodies, raw responses with timings,
latency and server build inside): for one public law passage the greedy first answer is invalid
and a sampled retry is valid. Never edited by hand. The answer cache is a temporary directory.
"""

import json
from pathlib import Path

import pytest
from model_selection import indomain_data as data
from model_selection import indomain_gen as gen
from model_selection import indomain_retry as retry

FIXTURE = Path(__file__).parent / "fixtures" / "indomain_retry_14b.json"
DOC = json.loads(FIXTURE.read_text(encoding="utf-8"))
ITEM = DOC["items"][0]
PASSAGE = data.Passage(**ITEM["passage"])
REPLIES = [a["response"]["choices"][0]["message"]["content"] for a in ITEM["attempts"]]
VERDICTS = [a["verdict"] for a in ITEM["attempts"]]
MODEL = DOC["model"]


@pytest.fixture(autouse=True)
def _cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(gen, "CACHE", tmp_path)


def _store(key: str, text: str) -> None:
    gen.CACHE.mkdir(parents=True, exist_ok=True)
    rec = {"model": MODEL, "prompt": data.GEN_PROMPT, "passage_id": key, "response": text}
    gen.cache_path(MODEL, data.GEN_PROMPT, key).write_text(json.dumps(rec), encoding="utf-8")


def _run(*, retries: int, max_calls: int) -> tuple[retry.Tally, list[tuple[str, int]]]:
    """``call`` replays the recorded answer of the requested attempt (never invents one)."""
    made: list[tuple[str, int]] = []

    def call(key: str, attempt: int, _p: data.Passage) -> None:
        assert key == retry.attempt_key(PASSAGE.id, attempt)
        made.append((key, attempt))
        _store(key, REPLIES[attempt])

    tally = retry.run_generate(
        [PASSAGE],
        lambda pid: retry.answers(MODEL, pid, retries),
        call,
        retries=retries,
        max_calls=max_calls,
        tally=retry.Tally(),
    )
    return tally, made


def test_the_fixture_is_a_real_recording_of_one_model() -> None:
    assert DOC["source"].startswith("real exchanges recorded by record_retry.py")
    assert MODEL == "openai_compatible_local/ministral-3-14b-instruct-2512"
    assert DOC["server"]["model_file"] == "Ministral-3-14B-Instruct-2512-Q4_K_M.gguf"
    first, *rest = ITEM["attempts"]
    assert (first["request"]["temperature"], first["request"]["seed"]) == (0.0, 42)
    for k, a in enumerate(rest, start=1):
        assert (a["request"]["temperature"], a["request"]["seed"]) == (
            gen.RETRY_TEMPERATURE,
            42 + k,
        )
    assert {a["response"]["model"] for a in ITEM["attempts"]} == {"ministral-3-14b-instruct-2512"}


def test_the_recorded_answers_are_judged_as_recorded() -> None:
    assert [retry.judge_answer(t, PASSAGE.text)[1] or "valid" for t in REPLIES] == VERDICTS
    assert VERDICTS[0] != "valid"
    assert VERDICTS[-1] == "valid"


def test_an_invalid_first_answer_is_asked_again_until_valid() -> None:
    tally, made = _run(retries=len(REPLIES), max_calls=10)
    assert [a for _, a in made] == list(range(len(REPLIES)))
    assert (tally.calls, tally.retries, tally.exhausted) == (len(REPLIES), len(REPLIES) - 1, 0)
    item, _ = retry.first_valid(retry.answers(MODEL, PASSAGE.id, len(REPLIES)), PASSAGE.text)
    assert item is not None
    assert item["evidence_span"] in PASSAGE.text


def test_zero_retries_is_one_call_and_counts_the_item_exhausted() -> None:
    tally, made = _run(retries=0, max_calls=1)  # the last attempt uses the last call of the budget
    assert made == [(PASSAGE.id, 0)]
    assert (tally.calls, tally.exhausted) == (1, 1)


def test_the_budget_stops_mid_item_and_a_rerun_continues_at_the_next_attempt() -> None:
    tally, made = _run(retries=len(REPLIES), max_calls=1)
    assert (tally.calls, tally.exhausted, made) == (1, 0, [(PASSAGE.id, 0)])
    tally, made = _run(retries=len(REPLIES), max_calls=10)
    assert made[0] == (retry.attempt_key(PASSAGE.id, 1), 1)
    assert tally.retries == tally.calls


def test_a_valid_cached_answer_makes_no_call() -> None:
    _store(retry.attempt_key(PASSAGE.id, 0), REPLIES[-1])
    tally, made = _run(retries=2, max_calls=10)
    assert made == []
    assert tally.calls == 0


def test_the_generation_schema_matches_the_validation_limits() -> None:
    span = gen.GEN_SCHEMA["properties"]["evidence_span"]
    assert (span["minLength"], span["maxLength"]) == (20, 400)
    assert set(gen.GEN_SCHEMA["required"]) == {"question", "evidence_span", "reference_answer"}


def test_an_old_greedy_retry_entry_is_never_read_as_a_sampled_retry() -> None:
    # before the review round a retry was cached as "<id>#retry1" with temperature 0
    _store(PASSAGE.id, REPLIES[0])
    _store(f"{PASSAGE.id}#retry1", REPLIES[-1])
    assert retry.answers(MODEL, PASSAGE.id, 2) == [REPLIES[0]]
    assert retry.attempt_key(PASSAGE.id, 1) == f"{PASSAGE.id}#retry1-t0.7-s43"
