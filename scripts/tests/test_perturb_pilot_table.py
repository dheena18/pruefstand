"""The pilot table renderer (T4.5): rates exclude not-applicable rows."""

from pathlib import Path

import pytest
from perturb_pilot_table import load_questions, main, render

from pruefstand.perturb.batch import item_id

QUESTIONS = ["Gilt das Kündigungsschutzgesetz?", "Können Sie helfen?", "Wie lang ist die Frist?"]
ID = [item_id(q) for q in QUESTIONS]
TSV = "\n".join(
    [
        f"{ID[0]}\tcompound_split\tvalid=True\tGilt das Gesetz zum Schutz vor Kündigungen?",
        f"{ID[1]}\tcompound_split\tvalid=False\treason=not_applicable\tKönnen Sie helfen?",
        f"{ID[2]}\tcompound_split\tvalid=False\treason=not_equivalent\tWie lang ist die Frist?",
        f"{ID[1]}\tregister\tvalid=True\tKannst du helfen?",
        f"{ID[2]}\tregister\tvalid=False\treason=unchanged\tWie lang ist die Frist?",
        "noise",
    ]
)


def test_rates_exclude_not_applicable_and_unchanged() -> None:
    out = render(QUESTIONS, TSV)
    assert "| compound_split | 1 | 2 | 50% |" in out
    assert "| register | 1 | 1 | 100% |" in out
    assert f"| {ID[0]} | compound_split | Gilt das Kündigungsschutzgesetz? |" in out


def test_main_prints_and_checks_usage(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    q = tmp_path / "q.txt"
    q.write_text("# c\n" + "\n".join(QUESTIONS) + "\n", encoding="utf-8")
    t = tmp_path / "o.tsv"
    t.write_text(TSV, encoding="utf-8")
    assert load_questions(q) == QUESTIONS
    assert main([str(q), str(t)]) == 0
    assert "validity rate" in capsys.readouterr().out
    assert main([]) == 2
