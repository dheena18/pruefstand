from pathlib import Path

import pytest
from check_code_limits import main


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _func(body_lines: int) -> str:
    return "def long_function() -> None:\n" + "    x = 1\n" * body_lines


def test_file_of_301_lines_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write(tmp_path, "scripts/big.py", "x = 1\n" * 301)
    assert main(["--root", str(tmp_path)]) == 1
    assert "301" in capsys.readouterr().out


def test_file_of_300_lines_passes(tmp_path: Path) -> None:
    _write(tmp_path, "scripts/ok.py", "x = 1\n" * 300)
    assert main(["--root", str(tmp_path)]) == 0


def test_function_with_51_body_lines_fails_and_is_named(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(tmp_path, "packages/p/mod.py", _func(51))
    assert main(["--root", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "long_function" in out
    assert "51" in out


def test_function_with_50_body_lines_passes(tmp_path: Path) -> None:
    _write(tmp_path, "packages/p/mod.py", _func(50))
    assert main(["--root", str(tmp_path)]) == 0


def test_apps_must_not_mention_datasets(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write(tmp_path, "apps/x/y.py", 'PATH = "datasets/core"\n')
    assert main(["--root", str(tmp_path)]) == 1
    assert "apps/x/y.py" in capsys.readouterr().out


def test_datasets_string_outside_apps_is_fine(tmp_path: Path) -> None:
    _write(tmp_path, "scripts/y.py", 'PATH = "datasets/core"\n')
    assert main(["--root", str(tmp_path)]) == 0
