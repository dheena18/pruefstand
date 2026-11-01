"""Extraction part of scripts/check_mermaid.sh (T0.4 S6b): numbering, nesting, line numbers."""

import os
import shutil
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_mermaid.sh"
BASH = shutil.which("bash") or "bash"


def _extract(docs: Path) -> list[tuple[str, str]]:
    """Run the extraction only; return (file:line, block text) in index order."""
    env = {**os.environ, "MERMAID_DOCS_DIR": str(docs), "MERMAID_EXTRACT_ONLY": "1"}
    result = subprocess.run(  # noqa: S603  # fixed argv, no shell
        [BASH, str(SCRIPT)], capture_output=True, text=True, check=False, env=env
    )
    assert result.returncode == 0, result.stderr
    blocks: list[tuple[str, str]] = []
    for line in result.stdout.splitlines():
        number, where, text = line.split("\t", 2)
        assert int(number) == len(blocks) + 1
        blocks.append((where, text.replace("\\n", "\n")))
    return blocks


def test_many_files_force_several_awk_runs_without_collisions(tmp_path: Path) -> None:
    for i in range(12):
        (tmp_path / f"f{i:02d}.md").write_text(
            f"# t\n\n```mermaid\nflowchart TD\n  A{i} --> B\n```\n", encoding="utf-8"
        )
    blocks = _extract(tmp_path)
    assert len(blocks) == 12
    assert [text for _, text in blocks] == [f"flowchart TD\n  A{i} --> B\n" for i in range(12)]
    assert blocks[3][0].endswith("f03.md:4")  # first line of the block body


def test_fence_nested_in_a_longer_fence_is_not_a_block(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text(
        "````md\n```mermaid\nnot a diagram ;;\n```\n````\n\n"
        "```mermaid\nflowchart TD\n  X --> Y\n```\n",
        encoding="utf-8",
    )
    blocks = _extract(tmp_path)
    assert [text for _, text in blocks] == ["flowchart TD\n  X --> Y\n"]
    assert blocks[0][0].endswith("a.md:8")


def test_other_fences_and_indented_blocks(tmp_path: Path) -> None:
    (tmp_path / "b.md").write_text(
        "```python\nx = 1\n```\n\n- item\n\n  ```mermaid\n  flowchart TD\n    P --> Q\n  ```\n",
        encoding="utf-8",
    )
    blocks = _extract(tmp_path)
    assert len(blocks) == 1
    assert "P --> Q" in blocks[0][1]


def test_crlf_files_keep_their_blocks(tmp_path: Path) -> None:
    (tmp_path / "c.md").write_bytes(
        b"# t\r\n\r\n```mermaid\r\nflowchart TD\r\n  A --> B\r\n```\r\n"
    )
    blocks = _extract(tmp_path)
    assert len(blocks) == 1
    assert "A --> B" in blocks[0][1]
    assert "\r" not in blocks[0][1]


def test_unterminated_fence_fails_naming_file_and_line(tmp_path: Path) -> None:
    (tmp_path / "u.md").write_text("# t\n\n```mermaid\nflowchart TD\n  A --> B\n", encoding="utf-8")
    env = {**os.environ, "MERMAID_DOCS_DIR": str(tmp_path), "MERMAID_EXTRACT_ONLY": "1"}
    result = subprocess.run(  # noqa: S603  # fixed argv, no shell
        [BASH, str(SCRIPT)], capture_output=True, text=True, check=False, env=env
    )
    assert result.returncode == 1
    assert "u.md:3" in result.stderr
    assert "unterminated" in result.stderr
