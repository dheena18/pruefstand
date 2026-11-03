"""``python -m pruefstand.perturb`` with the LLM perturbations: lines, passes, exit codes (T4.5)."""

from pathlib import Path

import pytest
from testsupport.loopback_script import serve_script
from testsupport.perturb_support import JUDGE, REWRITER, answers, client, verdict

from pruefstand.llm.client import LLMClient
from pruefstand.perturb.__main__ import main
from pruefstand.perturb.batch import item_id

Q = "Können Sie mir sagen, ob das Kündigungsschutzgesetz für meine Mitarbeiter gilt?"


def test_four_lines_with_valid_or_reason(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    rewrites = answers(
        "Können Sie mir sagen, ob das Gesetz zum Schutz vor Kündigungen für meine "
        "Mitarbeiter gilt?",
        "Darf ich dich fragen, ob das für meine Leute gilt?",
    )
    with (
        serve_script(rewrites) as (rb, _),
        serve_script(answers(verdict(1), verdict(0))) as (jb, _j),
    ):
        bases = {REWRITER: rb, JUDGE: jb}

        def factory(model: str, max_requests: int | None) -> LLMClient:
            return client(bases[model], model, max_requests=max_requests)

        argv = [
            Q,
            "--name",
            "register,compound_split,gender,colloquial",
            "--model",
            REWRITER,
            "--judge-model",
            JUDGE,
            "--store",
            str(tmp_path),
        ]
        assert main(argv, client_factory=factory) == 0
    lines = capsys.readouterr().out.splitlines()
    assert [ln.split("\t")[0] for ln in lines] == [
        "register",
        "compound_split",
        "gender",
        "colloquial",
    ]
    assert lines[0].split("\t")[1] == "valid=True"
    assert lines[1].split("\t")[1] == "valid=True"
    assert all("\t" in ln and ln.split("\t")[1].startswith("valid=") for ln in lines)
    assert "reason=" in lines[3] or "reason=" in lines[2]


def test_llm_name_without_model_is_exit_2(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([Q, "--name", "colloquial"]) == 2
    assert "--model" in capsys.readouterr().err


def test_pass_rewrite_then_validate(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    out = "Wann darf mein Chef mich rauswerfen?"
    q = "Unter welchen Voraussetzungen ist eine ordentliche Kündigung zulässig?"
    with serve_script(answers(out)) as (rb, rs):

        def f1(model: str, max_requests: int | None) -> LLMClient:
            return client(rb, model, max_requests=max_requests)

        base = [
            q,
            "--name",
            "colloquial",
            "--model",
            REWRITER,
            "--judge-model",
            JUDGE,
            "--store",
            str(tmp_path),
        ]
        assert main([*base, "--pass", "rewrite"], client_factory=f1) == 0
    assert capsys.readouterr().out.startswith("colloquial\trewritten\t1 new")
    with serve_script(answers(verdict(1))) as (jb, js):

        def f2(model: str, max_requests: int | None) -> LLMClient:
            return client(jb, model)

        assert main([*base, "--pass", "validate"], client_factory=f2) == 0
    line = capsys.readouterr().out.strip().split("\t")
    assert line[:3] == ["colloquial", "valid=True", out]
    assert js.posts() == 1
    assert rs.posts() == 1


def test_deterministic_names_still_work(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["Gilt die Frist ab 03.10.2026?", "--name", "dates"]) == 0
    assert capsys.readouterr().out.startswith("dates\tchanged\t")


def test_questions_file_prefixes_the_item_id(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    file = tmp_path / "q.txt"
    file.write_text("# pilot\nKönnen Sie mir helfen?\n\nHaben Sie Urlaub?\n", encoding="utf-8")

    argv = ["--questions", str(file), "--name", "register", "--model", REWRITER]
    with serve_script([]) as (base, state):

        def factory(model: str, max_requests: int | None) -> LLMClient:
            return client(base, model, max_requests=max_requests)

        assert main([*argv, "--judge-model", JUDGE], client_factory=factory) == 0
    assert state.posts() == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines == [
        f"{item_id('Können Sie mir helfen?')}\tregister\tvalid=True\tKannst du mir helfen?",
        f"{item_id('Haben Sie Urlaub?')}\tregister\tvalid=True\tHast du Urlaub?",
    ]


def test_no_question_is_exit_2(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--name", "dates"]) == 2
    assert "QUESTION" in capsys.readouterr().err
