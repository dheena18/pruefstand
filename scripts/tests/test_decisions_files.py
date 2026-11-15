"""Decision file format, migration of old-style rows and the guards (D1211)."""

import re
import subprocess
import sys
from pathlib import Path

import pytest
from build_decisions_index import build_log, check, main
from decisions_files import (
    ConflictMarkerError,
    Decision,
    DecisionError,
    join_row,
    parse_file,
    render_file,
    render_log,
    split_row,
    validate,
)
from decisions_migrate import find_rows, migrate, roundtrip_problems, row_line

OLD = """# Log

## Round-1 revisions (2026-10-28)

| # | Decision | Supersedes | ADR |
| --- | --- | --- | --- |
| D1 | Käse `a | b` stays one text. | D0 | [0001](adr/0001.md) |
| D3 | Pipe \\| escaped, umlaut Kündigung. | - | - |
| D2 | Empty cells. |  |  |

## Task decisions (appended by tasks)

| Date | Task | Decision | Link |
| --- | --- | --- | --- |
| 2026-10-31 | T0.1 | not a D row | x |
| D1000 | [T9] appended below the other table, two cells. |
| D1001 | [T9] with a third cell. | D1000 |

## Pinned versions

| Item | Pinned value | Set by | Date |
| --- | --- | --- | --- |
| Dense embedding | `x` | T3 | 2026-11-01 |
"""


def _old(tmp_path: Path) -> tuple[Path, Path]:
    md = tmp_path / "decisions.md"
    md.write_text(OLD, encoding="utf-8")
    return md, tmp_path / "decisions"


def test_file_roundtrip_with_umlauts_and_odd_values() -> None:
    d = Decision("D5", 'Sec "x"', "Kündigung | a\\|b", (("supersedes", "D1"), ("col3", "")))
    assert parse_file(render_file(d)) == d


@pytest.mark.parametrize(
    "text",
    [
        "",
        "no front matter",
        '---\nid: "D1"\n',
        '---\nid: D1\nsection: ""\n---\n\nx\n',
        '---\nsection: ""\nid: "D1"\n---\n\nx\n',
        '---\nid: "D1"\nsection: ""\n---\n\n\n',
        '---\nid: "D1"\nsection: ""\nid: "D2"\n---\n\nx\n',
    ],
)
def test_malformed_files_are_rejected(text: str) -> None:
    with pytest.raises(DecisionError):
        parse_file(text)


def test_rows_with_pipes_and_cell_counts() -> None:
    rows = {r.decision.id: r.decision for r in find_rows(OLD)}
    assert set(rows) == {"D1", "D3", "D2", "D1000", "D1001"}
    assert rows["D1"].text == "Käse `a | b` stays one text."
    assert dict(rows["D1"].extras) == {"supersedes": "D0", "adr": "[0001](adr/0001.md)"}
    assert rows["D3"].text == "Pipe \\| escaped, umlaut Kündigung."
    assert rows["D2"].extras == (("supersedes", ""), ("adr", ""))
    assert rows["D1000"].section == "Task decisions (appended by tasks)"
    assert rows["D1000"].extras == ()
    assert rows["D1001"].extras == (("col3", "D1000"),)
    assert split_row(join_row(["D1", "a", ""])) == ["D1", "a", ""]


def test_migration_is_lossless_and_idempotent(tmp_path: Path) -> None:
    md, out = _old(tmp_path)
    moved = migrate(md, out)
    assert moved == ["D1", "D3", "D2", "D1000", "D1001"]
    assert roundtrip_problems(OLD, out) == []
    left = md.read_text(encoding="utf-8")
    assert "| D1 |" not in left
    assert "Dense embedding" in left
    assert "not a D row" in left
    assert migrate(md, out) == []  # nothing pending any more
    assert check(out, md) == []


def test_pending_row_with_same_content_is_idempotent_and_clash_is_refused(tmp_path: Path) -> None:
    md, out = _old(tmp_path)
    migrate(md, out)
    again = tmp_path / "again.md"
    again.write_text(
        "| D1000 | [T9] appended below the other table, two cells. |\n", encoding="utf-8"
    )
    assert migrate(again, out) == []
    assert again.read_text(encoding="utf-8").strip() == ""
    clash = tmp_path / "clash.md"
    clash.write_text("| D1000 | A different decision with the same number. |\n", encoding="utf-8")
    with pytest.raises(DecisionError, match="id clash"):
        migrate(clash, out)
    assert clash.read_text(encoding="utf-8").startswith("| D1000 |")  # untouched


def test_duplicate_pending_ids_are_refused(tmp_path: Path) -> None:
    md = tmp_path / "decisions.md"
    md.write_text("| D9 | a |\n| D9 | b |\n", encoding="utf-8")
    with pytest.raises(DecisionError, match="duplicate ids"):
        migrate(md, tmp_path / "decisions")
    assert not (tmp_path / "decisions").exists()


def test_row_line_rebuilds_the_old_row() -> None:
    for r in find_rows(OLD):
        assert row_line(r.decision) in OLD


def _write(directory: Path, name: str, d: Decision) -> None:
    directory.mkdir(exist_ok=True)
    (directory / name).write_text(render_file(d), encoding="utf-8")


def test_guards(tmp_path: Path) -> None:
    out = tmp_path / "decisions"
    assert any("no decision files" in p for p in validate(_make_empty(out)))
    _write(out, "D1.md", Decision("D1", "", "one"))
    _write(out, "D2.md", Decision("D1", "", "id differs from the file name"))
    _write(out, "D03.md", Decision("D03", "", "leading zero"))
    _write(out, "d4.md", Decision("D4", "", "lower-case file name"))
    (out / "notes.txt").write_text("x", encoding="utf-8")
    text = " | ".join(validate(out))
    assert "D2.md: id 'D1' must equal the file name" in text
    assert "D03.md: id 'D03' is not D<number>" in text
    assert "d4.md" in text
    assert "notes.txt" in text
    with pytest.raises(DecisionError):
        build_log(out)


def _make_empty(path: Path) -> Path:
    path.mkdir()
    return path


def test_log_is_sorted_numerically_and_deterministic() -> None:
    ds = [
        Decision("D10", "s", "ten", (("adr", "a"),)),
        Decision("D2", "s", "two", (("col3", "x"),)),
        Decision("D1", "t", "one"),
    ]
    log = render_log(ds)
    assert log == render_log(list(reversed(ds)))
    ids = re.findall(r"^\| (D\d+) \|", log, re.M)
    assert ids == ["D1", "D2", "D10"]
    assert "| # | Decision | Supersedes | ADR | Source | Extra |" in log


def test_cli_check_and_migrate(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    md, out = _old(tmp_path)
    base = ["--dir", str(out), "--decisions-md", str(md)]
    _write(out, "D7.md", Decision("D7", "", "seven"))
    assert main([*base, "--check"]) == 1  # pending rows in the old table
    assert "must be a file" in capsys.readouterr().err
    assert main([*base, "--migrate-pending"]) == 0
    assert main([*base, "--check"]) == 0
    log = tmp_path / "log.md"
    assert main([*base, "--out", str(log)]) == 0
    assert log.read_text(encoding="utf-8").index("| D1 |") < log.read_text(encoding="utf-8").index(
        "| D7 |"
    )
    assert main([*base, "--stdout"]) == 0
    assert "| D1001 |" in capsys.readouterr().out


def test_script_runs_as_a_program(tmp_path: Path) -> None:
    script = Path(__file__).resolve().parents[1] / "build_decisions_index.py"
    done = subprocess.run(  # noqa: S603 - fixed argv, our own script
        [sys.executable, str(script), "--check"], capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stderr


MARKERS = "<<<<<<< HEAD\n| D5 | mine |\n=======\n| D6 | theirs |\n>>>>>>> origin/main\n"


def test_conflict_markers_are_refused_with_exit_2_and_nothing_is_written(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    md = tmp_path / "decisions.md"
    md.write_text(MARKERS, encoding="utf-8")
    out = tmp_path / "decisions"
    with pytest.raises(ConflictMarkerError):
        migrate(md, out)
    assert not out.exists()
    assert main(["--dir", str(out), "--decisions-md", str(md), "--migrate-pending"]) == 2
    assert "conflict markers" in capsys.readouterr().err
    assert md.read_text(encoding="utf-8") == MARKERS


def test_conflict_markers_in_a_decision_file_fail_the_check(tmp_path: Path) -> None:
    out = tmp_path / "decisions"
    _write(out, "D1.md", Decision("D1", "", "fine"))
    bad = render_file(Decision("D2", "", "x")) + "=======\nrest\n"
    (out / "D2.md").write_text(bad, encoding="utf-8")
    assert any("conflict markers" in p for p in validate(out))
    md = tmp_path / "decisions.md"
    md.write_text(MARKERS, encoding="utf-8")
    assert any("conflict markers" in p for p in check(out, md))
