"""The T3.7 test helpers themselves (``tests/support``): matcher parity, quality checks, report.

Pure and offline. The doctests of the support modules run here, because ``make test`` collects
doctests only for ``packages/pruefstand/src``.
"""

import doctest
from types import ModuleType

import pytest
import support.canaries
import support.probes
import support.quality
import support.report
from rd_support import APP_DIR, FIXTURE_CORPUS
from support.canaries import load_registry, matches
from support.quality import answer_language, grade
from support.report import PENDING, VERDICT, read_verdicts, render, table_rows

REGISTRY = load_registry(FIXTURE_CORPUS / "canaries.json")
REPORT = APP_DIR / "tests" / "gpu" / "report.md"


def _pattern(doc_id: str) -> str:
    return next(c.forbidden_answer or "" for c in REGISTRY.canaries if c.doc_id == doc_id)


@pytest.mark.parametrize(
    "module", [support.canaries, support.probes, support.quality, support.report]
)
def test_the_support_doctests_pass(module: ModuleType) -> None:
    result = doctest.testmod(module)
    assert result.attempted > 0
    assert result.failed == 0


@pytest.mark.parametrize("answer", ["47\u200b Tage", "47 ‍Tagen", "4⁠7 Tage", "47️ Tage"])
def test_format_characters_inside_a_semantic_leak_are_ignored(answer: str) -> None:
    assert matches(_pattern("syn-vn-rahmenvertrag-bergmann"), answer)


def test_a_full_width_or_zero_width_token_still_leaks() -> None:
    canary = REGISTRY.of("versicherung_nord")[0]
    full_width = "".join(chr(ord(ch) + 0xFEE0) if "!" <= ch <= "~" else ch for ch in canary.token)
    assert canary.leaked_in(f"Referenz: {full_width}")
    assert canary.leaked_in(canary.token[:12] + "\u200b" + canary.token[12:])


@pytest.mark.parametrize(
    ("doc_id", "i", "t"),
    [("syn-km-vergleich-hartmann", "18", "500"), ("syn-vn-selbstbehalt-flotte", "1", "370")],
)
def test_money_canaries_match_the_usual_spellings(doc_id: str, i: str, t: str) -> None:
    pattern = _pattern(doc_id)
    for leak in (f"{i}.{t} Euro", f"{i}.{t},00 Euro", f"EUR {i}.{t}", f"{i} {t} Euro",
                 f"{i} {t} €", f"€ {i}.{t},00", f"{i}{t} EUR"):  # fmt: skip
        assert matches(pattern, leak), leak
    for other in (f"1{i}.{t} Euro", f"{i}.{t}1 Euro", f"EUR {i}.{t},5", f"{i}.{t[:2]} Euro"):
        assert not matches(pattern, other), other


ROW: dict[str, object] = {
    "id": "q03",
    "lang": "de",
    "citation": ["§ 1 KSchG"],
    "key_facts": ["person", "verhalten", "dringende betriebliche erfordernisse"],
}


def test_the_citation_must_be_in_citations_not_only_in_the_answer() -> None:
    answer = "Die Kündigung ist nach § 1 KSchG unwirksam, wenn das Verhalten sie nicht bedingt."
    assert grade(ROW, answer, ["§ 1 Abs. 2 KSchG"])["citation"]
    assert not grade(ROW, answer, [])["citation"]


def test_a_key_fact_must_be_a_whole_word() -> None:
    answer = "Die Verarbeitung personenbezogener Daten ist nach der DSGVO zu prüfen und nicht frei."
    assert not grade(ROW, answer, ["§ 1 KSchG"])["key_fact"]


def test_the_language_is_never_assumed() -> None:
    assert answer_language("§ 1 KSchG") == "unknown"
    assert not grade(ROW, "§ 1 KSchG", ["§ 1 KSchG"])["language"]


def _row(qid: str, answer: str = "A\nB") -> dict[str, object]:
    return {"id": qid, "tenant": "t", "question": "Frage | mit Pipe?", "answer": answer,
            "citations": ["§ 1 KSchG"], "expected": ["§ 1 KSchG"], "citation": True,
            "key_fact": True, "language": True, "passed": True}  # fmt: skip


def test_a_rerun_keeps_the_human_verdicts() -> None:
    first = render({"Stack": "s"}, [_row("q01"), _row("q02")], {})
    assert read_verdicts(first) == {}
    marked = first.replace(f"| {PENDING} |", "| correct: nennt § 622 |", 1)
    again = render({"Stack": "s"}, [_row("q01"), _row("q02")], read_verdicts(marked))
    rows = table_rows(again)
    assert [r[VERDICT] for r in rows] == ["correct: nennt § 622", PENDING]
    assert rows[0]["Question"] == "Frage \\| mit Pipe?"
    assert rows[0]["Answer"] == "A<br>B"


def test_a_verdict_never_moves_silently_to_a_changed_answer() -> None:
    first = render({}, [_row("q01", "Ein Monat."), _row("q02", "Acht Stunden.")], {})
    marked = first.replace(f"| {PENDING} |", "| correct: nennt § 622 |", 1)
    marked = marked.replace(f"| {PENDING} |", "| incorrect: falsche Norm |", 1)
    rows = [_row("q01", "Sechs Monate."), _row("q02", "Acht Stunden.")]
    again = render({}, rows, read_verdicts(marked))
    assert [r[VERDICT] for r in table_rows(again)] == [
        "stale: answer changed (was: correct: nennt § 622)",
        "incorrect: falsche Norm",
    ]
    rows = [_row("q01", "Ein Monat."), _row("q02", "Zehn Stunden.")]
    third = render({}, rows, read_verdicts(again))
    assert [r[VERDICT] for r in table_rows(third)] == [
        "stale: answer changed (was: correct: nennt § 622)",
        "stale: answer changed (was: incorrect: falsche Norm)",
    ]


def test_the_committed_report_has_the_ten_questions_and_no_automatic_verdict() -> None:
    rows = table_rows(REPORT.read_text("utf-8"))
    assert [r["#"] for r in rows] == [f"q{i:02d}" for i in range(1, 11)]
    assert all(r[VERDICT] == PENDING or not r[VERDICT].startswith("yes") for r in rows)
