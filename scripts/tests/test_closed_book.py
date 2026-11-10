"""``scripts/closed_book.py``: closed-book heuristic, re-tagging, direct endpoint call (S4).

The heuristic runs on real German reference answers; the endpoint call is checked against the
scripted loopback server (request shape only: no model is behind it, so no knowledge claim is made).
"""

import http.client
import json
from pathlib import Path
from typing import NoReturn

import pytest
from closed_book import (
    TAG_PREFIX,
    content_recall,
    content_words,
    knows_closed_book,
    main,
    retag,
    tag_cases,
)
from testsupport.gpu_files import SHIPPED_CATALOGUE, SHIPPED_ENDPOINTS
from testsupport.loopback_script import serve_script
from testsupport.pipeline_support import case_rows, write_dataset
from testsupport.run_builders import make_case

from pruefstand.core.errors import PruefstandError
from pruefstand.core.models.testcase import TestCase

MODEL = "ollama/qwen3.8:27b-q8_0"
OTHER = "ollama/qwen3:4b"
REFERENCE = "Einen Monat zum Ende eines Kalendermonats."
GOOD = "Nach § 622 Abs. 2 Nr. 1 BGB einen Monat, jeweils zum Ende eines Kalendermonats."


def kuendigung(index: int = 0, **changes: object) -> TestCase:
    return make_case(
        index,
        question="Wie lang ist die Kündigungsfrist in der Probezeit?",
        reference_answer=REFERENCE,
        gold_citations=("§ 622 Abs. 2 BGB",),
        split="core",
        **changes,
    )


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRUEFSTAND_GPU_CATALOGUE", str(SHIPPED_CATALOGUE))
    monkeypatch.setenv("PRUEFSTAND_GPU_ENDPOINTS", str(SHIPPED_ENDPOINTS))
    monkeypatch.setenv("PRUEFSTAND_LOCK_HELD", "1")


def test_citation_and_content_words_together_tag_the_case() -> None:
    assert knows_closed_book(kuendigung(), GOOD)


def test_the_citation_alone_is_not_enough() -> None:
    assert not knows_closed_book(kuendigung(), "Das regelt § 622 Abs. 2 BGB.")


def test_the_content_without_a_citation_is_not_enough() -> None:
    assert not knows_closed_book(kuendigung(), "einen Monat, jeweils zum Ende eines Kalendermonats")


def test_a_wrong_absatz_is_not_a_match() -> None:
    answer = "Nach § 622 Abs. 3 BGB einen Monat, jeweils zum Ende eines Kalendermonats."
    assert not knows_closed_book(kuendigung(), answer)


def test_an_unknown_answer_is_not_tagged() -> None:
    assert not knows_closed_book(kuendigung(), "Das weiß ich nicht.")
    assert not knows_closed_book(kuendigung(), "Unbekannt")


def test_the_reference_citation_does_not_count_as_content() -> None:
    reference = "Vier Wochen zum Fünfzehnten oder zum Monatsende (§ 622 Abs. 1 BGB)."
    words = content_words(reference)
    assert not {"622", "abs", "bgb"} & words
    assert content_recall(reference, "vier wochen zum fünfzehnten oder monatsende") == 1.0


def test_inflected_forms_match() -> None:
    assert content_words("Kalendermonats") == content_words("Kalendermonat")


def test_the_threshold_is_eighty_percent() -> None:
    case = kuendigung().model_copy(
        update={
            "reference_answer": "Die Frist beträgt vier Wochen zum Fünfzehnten oder Monatsende."
        }
    )
    four_of_five = "Nach § 622 Abs. 2 BGB vier Wochen zum Fünfzehnten oder Monatsende"
    assert knows_closed_book(case, four_of_five.replace("Fünfzehnten", "Fünfzehnten Frist"))
    assert not knows_closed_book(case, "Nach § 622 Abs. 2 BGB vier Wochen")


def test_a_case_without_reference_or_citation_is_never_tagged() -> None:
    assert not knows_closed_book(kuendigung().model_copy(update={"gold_citations": ()}), GOOD)
    assert not knows_closed_book(kuendigung().model_copy(update={"reference_answer": None}), GOOD)


def test_tagging_is_idempotent() -> None:
    once = retag(kuendigung(), MODEL, knew=True, drop_other_models=False)
    twice = retag(once, MODEL, knew=True, drop_other_models=False)
    assert once.tags == (TAG_PREFIX + MODEL,) == twice.tags


def test_retag_removes_the_tag_of_another_model_only() -> None:
    case = kuendigung(tags=("closed_book:ollama/a", "other"))
    kept = retag(case, MODEL, knew=True, drop_other_models=False)
    assert kept.tags == ("closed_book:ollama/a", "other", TAG_PREFIX + MODEL)
    replaced = retag(case, MODEL, knew=True, drop_other_models=True)
    assert replaced.tags == ("other", TAG_PREFIX + MODEL)


def test_the_tag_of_this_model_is_recomputed() -> None:
    case = kuendigung(tags=(TAG_PREFIX + MODEL,))
    assert retag(case, MODEL, knew=False, drop_other_models=False).tags == ()


def test_unanswerable_cases_are_not_asked() -> None:
    asked: list[str] = []
    refusal = make_case(
        1, split="core", category="unanswerable", expect_refusal=True, reference_answer=None
    )

    def ask(question: str) -> str:
        asked.append(question)
        return GOOD

    out = tag_cases([kuendigung(), refusal], MODEL, ask, drop_other_models=False)
    assert len(asked) == 1
    assert [bool(c.tags) for c in out] == [True, False]


def _dataset(tmp_path: Path, cases: list[TestCase]) -> Path:
    return write_dataset(tmp_path, {"core": case_rows(cases)})


def test_main_rewrites_the_split_and_prints_the_count(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    directory = _dataset(tmp_path, [kuendigung(0), kuendigung(1, tags=("closed_book:ollama/a",))])
    answers = iter([GOOD, "Unbekannt"])
    args = ["--model", MODEL, "--split", "core", "--dataset", str(directory), "--retag"]
    assert main(args, asker=lambda _q: next(answers)) == 0
    assert capsys.readouterr().out.strip() == "tagged=1/2"
    rows = [json.loads(x) for x in (directory / "core.jsonl").read_text("utf-8").splitlines()]
    assert [r["tags"] for r in rows] == [[TAG_PREFIX + MODEL], []]


def test_a_missing_lock_and_an_external_model_are_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    directory = _dataset(tmp_path, [kuendigung()])
    base = ["--dataset", str(directory)]
    assert main(["--model", "openai/gpt", *base], asker=lambda _q: GOOD) == 2
    monkeypatch.delenv("PRUEFSTAND_LOCK_HELD")
    assert main(["--model", MODEL, *base]) == 2
    assert "pruefstand-lock" in capsys.readouterr().err


def test_the_direct_call_has_no_retrieval_temperature_zero_and_thinking_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    directory = _dataset(tmp_path, [kuendigung()])
    with serve_script(content=GOOD) as (origin, state):
        monkeypatch.setenv("OLLAMA_GPU0_URL", origin)
        assert main(["--model", MODEL, "--dataset", str(directory)]) == 0
    assert capsys.readouterr().out.strip() == "tagged=1/1"
    (seen,) = [s for s in state.seen if s.path == "/api/chat"]
    body = seen.body
    assert body["model"] == "qwen3.8:27b-q8_0"
    assert body["think"] is False
    assert body["stream"] is False
    assert body["options"]["temperature"] == 0.0  # type: ignore[index]  # JSON body, shape known
    roles = [m["role"] for m in body["messages"]]  # type: ignore[attr-defined]  # same
    assert roles == ["system", "user"]
    assert "Kündigungsfrist" in json.dumps(body, ensure_ascii=False)


def test_a_failing_endpoint_exits_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    directory = _dataset(tmp_path, [kuendigung()])
    monkeypatch.setenv("OLLAMA_GPU0_URL", "http://127.0.0.1:9")  # nothing listens (discard port)
    assert main(["--model", MODEL, "--dataset", str(directory)]) == 1
    assert "model call failed" in capsys.readouterr().err
    assert "tags" not in (directory / "core.jsonl").read_text("utf-8").replace('"tags": []', "")


def test_a_citation_does_not_eat_the_first_letter_of_the_next_word() -> None:
    words = content_words("Laut § 622 vier Wochen zum Monatsende")
    assert words == content_words("Laut vier Wochen zum Monatsende")
    assert "vier" in content_words("Laut § 622 vier Wochen zum Monatsende")


def test_a_negated_answer_is_not_the_same_statement() -> None:
    reference = "Eine Kündigung ist zulässig."
    case = kuendigung().model_copy(update={"reference_answer": reference})
    assert knows_closed_book(case, "Nach § 622 Abs. 2 BGB ist eine Kündigung zulässig.")
    assert not knows_closed_book(case, "Nach § 622 Abs. 2 BGB ist eine Kündigung nicht zulässig.")


def test_a_negation_in_the_reference_must_be_in_the_answer() -> None:
    reference = "Eine Kündigung ist nicht zulässig."
    case = kuendigung().model_copy(update={"reference_answer": reference})
    assert not knows_closed_book(case, "Nach § 622 Abs. 2 BGB ist eine Kündigung zulässig.")
    assert knows_closed_book(case, "Nach § 622 Abs. 2 BGB ist eine Kündigung nicht zulässig.")


def test_a_failed_call_keeps_the_finished_part_of_the_run(tmp_path: Path) -> None:
    directory = _dataset(tmp_path, [kuendigung(0), kuendigung(1), kuendigung(2)])
    answers = iter([GOOD, GOOD])

    def ask(_question: str) -> str:
        try:
            return next(answers)
        except StopIteration:
            msg = "model call failed"
            raise PruefstandError(msg) from None

    assert main(["--model", MODEL, "--dataset", str(directory)], asker=ask) == 1
    rows = [json.loads(x) for x in (directory / "core.jsonl").read_text("utf-8").splitlines()]
    assert [bool(r["tags"]) for r in rows] == [True, True, False]


@pytest.mark.parametrize(
    "error", [ConnectionResetError, http.client.IncompleteRead, http.client.RemoteDisconnected]
)
def test_connection_errors_while_reading_are_exit_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: type[Exception]
) -> None:
    directory = _dataset(tmp_path, [kuendigung()])
    monkeypatch.setenv("OLLAMA_GPU0_URL", "http://127.0.0.1:9")

    def broken(*_a: object, **_k: object) -> NoReturn:
        raise error(b"") if error is http.client.IncompleteRead else error()

    monkeypatch.setattr("closed_book.urllib.request.urlopen", broken)
    assert main(["--model", MODEL, "--dataset", str(directory)]) == 1
