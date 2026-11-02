"""CLI helper ``python -m pruefstand.perturb`` (T4.4, S4)."""

import runpy
import sys

import pytest

from pruefstand.perturb.__main__ import main

Q = "Gilt § 622 BGB ab 03.10.2026 für 1.000,50 €?"


def test_single_name(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([Q, "--name", "dates"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out == ["dates\tchanged\tGilt § 622 BGB ab 3. Oktober 2026 für 1.000,50 €?"]


def test_all_prints_one_line_per_perturbation(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([Q, "--name", "all", "--seed", "1"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert [ln.split("\t")[0] for ln in lines] == [
        "umlaut_translit",
        "eszett",
        "numbers",
        "dates",
        "citation_style",
        "abbreviations",
        "typos",
    ]
    by_name = {ln.split("\t")[0]: ln.split("\t") for ln in lines}
    assert by_name["umlaut_translit"][1] == "changed"
    assert by_name["umlaut_translit"][2] == "Gilt § 622 BGB ab 03.10.2026 fuer 1.000,50 €?"
    assert by_name["eszett"][1] == "unchanged"
    assert by_name["numbers"][2].endswith("1000.50 EUR?")
    assert "Paragraph 622 des Bürgerlichen Gesetzbuchs" in by_name["citation_style"][2]
    assert by_name["abbreviations"][1] == "unchanged"


def test_unknown_name_exits_nonzero(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([Q, "--name", "nope"]) == 2
    assert "nope" in capsys.readouterr().err


def test_runs_as_module(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["pruefstand.perturb", Q, "--name", "eszett"])
    monkeypatch.delitem(sys.modules, "pruefstand.perturb.__main__")
    with pytest.raises(SystemExit) as exit_info:
        runpy.run_module("pruefstand.perturb", run_name="__main__")
    assert exit_info.value.code == 0
    assert capsys.readouterr().out.startswith("eszett\tunchanged\t")
