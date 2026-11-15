"""Tests of scripts/check_self_matching_pgrep.py (positive and negative cases)."""

from pathlib import Path

import pytest
from check_self_matching_pgrep import file_findings, main, offends, scan_text

BAD = [
    "pkill -f worker",
    "pgrep -f 'worker --flag'",
    'pkill -9 -f "my loop"',
    "pkill -TERM -f poll.sh",
    "pgrep -lf worker",
    "pgrep --full worker",
    "ssh vm 'pkill -f ollama'",
    'ssh vm "pgrep -f serve"',
    "ssh -p 22 host \"pkill -f 'x y'\"",
    "ssh vm 'cd /x && pkill -f watcher; echo done'",
    "kill $(pgrep -f $PATTERN)",
    "/usr/bin/pkill -f thing",
    "sudo pkill -f thing || true",
    "bash -c 'pgrep -f loop'",
    "echo x | pkill -f y",
]
GOOD = [
    "pgrep -f '[w]orker'",
    "pkill -f '[p]oll.sh'",
    "ssh vm 'pkill -f [o]llama'",
    "pgrep -x ollama",
    "pgrep -fx 'exact line'",
    "pkill -x worker",
    "pkill -P 123",
    "pgrep -u me -x ollama",
    "pkill -f thing -P 1",
    "pgrep -F /run/x.pid",
    "pkill --exact thing",
    'kill "$(cat /run/x.pid)"',
    "pgrep_pids() { pgrep -u me -x ollama; }",
    "# pkill -f worker is forbidden",
    "pkill -f worker  # selfmatch-ok: unique token",
    "echo pgrep",
    "pgrep ollama",
    "pkill -9 worker",
]


@pytest.mark.parametrize("line", BAD)
def test_offenders(line: str) -> None:
    assert [n for n, _ in scan_text(line)] == [1]


@pytest.mark.parametrize("line", GOOD)
def test_accepted(line: str) -> None:
    assert list(scan_text(line)) == []


def test_heredoc_bodies_and_line_numbers_are_scanned() -> None:
    text = "ok\nssh vm bash -s <<'EOF'\nset -e\npkill -f runner\nEOF\n"
    assert [n for n, _ in scan_text(text)] == [4]


def test_offends_on_token_lists() -> None:
    assert offends(["-f", "x"])
    assert not offends(["-f", "[x]"])
    assert not offends(["x"])


def test_shell_files_makefiles_and_workflows(tmp_path: Path) -> None:
    (tmp_path / "a.sh").write_text("#!/bin/bash\npkill -f a\n", encoding="utf-8")
    (tmp_path / "noext").write_text("#!/usr/bin/env bash\npgrep -f b\n", encoding="utf-8")
    (tmp_path / "mk").mkdir()
    (tmp_path / "mk" / "x.mk").write_text("stop:\n\tpkill -f c\n", encoding="utf-8")
    (tmp_path / "Makefile").write_text("stop:\n\tpkill -f d\n", encoding="utf-8")
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "w.yml").write_text(
        "on: push\njobs:\n  j:\n    runs-on: x\n    steps:\n"
        "      - run: |\n          echo hi\n          pkill -f e\n"
        "      - name: fine\n        run: pkill -f '[f]'\n"
        "      - name: other\n        with:\n          note: pkill -f g\n",
        encoding="utf-8",
    )
    (tmp_path / "doc.md").write_text("pkill -f docs are not scanned\n", encoding="utf-8")
    (tmp_path / "t.py").write_text("x = 'pkill -f py is not scanned'\n", encoding="utf-8")
    (tmp_path / "py_script").write_text("#!/usr/bin/env python3\n# pkill -f\n", encoding="utf-8")
    found = {
        rel.split(":")[0]
        for p in tmp_path.rglob("*")
        if p.is_file()
        for rel in file_findings(p, tmp_path)
    }
    assert found == {"a.sh", "noext", "mk/x.mk", "Makefile", ".github/workflows/w.yml"}
    lines = file_findings(wf / "w.yml", tmp_path)
    assert len(lines) == 1
    assert "pkill -f e" in lines[0]


def test_main_reports_and_exits(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "ok.sh").write_text("pgrep -x a\n", encoding="utf-8")
    assert main([str(tmp_path)]) == 0
    assert "ok: 1 files checked" in capsys.readouterr().out
    (tmp_path / "bad.sh").write_text("pkill -f a\n", encoding="utf-8")
    assert main([str(tmp_path)]) == 1
    assert "bad.sh:1:" in capsys.readouterr().out
