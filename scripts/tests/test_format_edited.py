import io
import json
from pathlib import Path

import pytest
from hooks.format_edited import main


def _payload(path: Path) -> io.StringIO:
    return io.StringIO(json.dumps({"tool_input": {"file_path": str(path)}}))


def test_python_file_is_formatted(tmp_path: Path) -> None:
    target = tmp_path / "repo" / "bad.py"
    target.parent.mkdir()
    target.write_text("x=1\n", encoding="utf-8")
    assert main(_payload(target), root=tmp_path / "repo") == 0
    assert target.read_text(encoding="utf-8") == "x = 1\n"


def test_markdown_file_is_untouched(tmp_path: Path) -> None:
    target = tmp_path / "repo" / "notes.md"
    target.parent.mkdir()
    target.write_text("x=1  \n", encoding="utf-8")
    assert main(_payload(target), root=tmp_path / "repo") == 0
    assert target.read_text(encoding="utf-8") == "x=1  \n"


def test_path_outside_repo_is_untouched(tmp_path: Path) -> None:
    (tmp_path / "repo").mkdir()
    target = tmp_path / "other.py"
    target.write_text("x=1\n", encoding="utf-8")
    assert main(_payload(target), root=tmp_path / "repo") == 0
    assert target.read_text(encoding="utf-8") == "x=1\n"


def test_invalid_json_exits_zero_with_message(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(io.StringIO("not json"), root=Path.cwd()) == 0
    assert capsys.readouterr().out
