"""Tests of scripts/check_self_matching_pgrep.py (positive and negative cases)."""

from pathlib import Path

import pytest
from check_self_matching_pgrep import file_findings, main
from pgrep_tokens import offends, scan_text

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
    "pkill -HUP -f worker",
    "pkill -STOP -f worker",
    "pkill -SIGTERM -f worker",
    "pkill -9 -f worker",
    "pkill -f -- -x",
    "pgrep -fa worker",
    "ssh vm 'pkill -USR1 -f worker'",
    'HEALTHCHECK CMD ["pgrep", "-f", "worker"]',
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
    "pkill -HUP -x worker",
    "pkill -HUP -f '[w]orker'",
    "pkill -f -- '[w]orker'",
    'HEALTHCHECK CMD ["pgrep", "-x", "worker"]',
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


def test_backslash_continued_lines_are_joined() -> None:
    text = "echo a\nsudo pgrep \\\n    -f worker\necho b\n"
    assert [n for n, _ in scan_text(text)] == [2]
    safe = "pgrep \\\n  -x worker\n"
    assert list(scan_text(safe)) == []
    marked = "pkill \\\n  -f worker  # selfmatch-ok: unique token\n"
    assert list(scan_text(marked)) == []


@pytest.mark.parametrize(
    "rel",
    [
        "run.zsh",
        "units/app.service",
        "Dockerfile",
        "docker/Dockerfile.app",
        "x.dockerfile",
        "mk/stop.mk",
        ".github/actions/setup/action.yml",
    ],
)
def test_more_file_kinds_are_scanned(tmp_path: Path, rel: str) -> None:
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if rel.endswith("action.yml"):
        body = (
            "runs:\n  using: composite\n  steps:\n    - shell: bash\n      run: pkill -f worker\n"
        )
    elif rel.endswith(".service"):
        body = "[Service]\nExecStop=/usr/bin/pkill -f worker\n"
    elif "ocker" in rel:
        body = "HEALTHCHECK CMD pgrep -f worker || exit 1\n"
    else:
        body = "pkill -f worker\n"
    path.write_text(body, encoding="utf-8")
    assert len(file_findings(path, tmp_path)) == 1


def test_python_command_strings_are_scanned(tmp_path: Path) -> None:
    source = (
        "import os\nimport subprocess\n\n"
        "subprocess.run(['pkill', '-f', 'worker'], check=False)\n"
        "subprocess.run('pgrep -f worker', shell=True, check=False)\n"
        "os.system(f'pkill -HUP -f {name}')\n"
        "subprocess.check_output(['ssh', host, 'pkill -f worker'])\n"
        "subprocess.run(['pkill', '-f', '[w]orker'], check=False)\n"
        "subprocess.run(['pgrep', '-x', 'worker'], check=False)\n"
        "subprocess.run('pkill -f x', shell=True)  # selfmatch-ok: unique\n"
        "print('pkill -f is not a command here')\n"
        "TEXT = 'pkill -f worker'\n"
    )
    path = tmp_path / "t.py"
    path.write_text(source, encoding="utf-8")
    lines = sorted(int(f.split(":")[1]) for f in file_findings(path, tmp_path))
    assert lines == [4, 5, 6, 7]


def test_python_syntax_errors_are_skipped(tmp_path: Path) -> None:
    path = tmp_path / "broken.py"
    path.write_text("def (:\n", encoding="utf-8")
    assert file_findings(path, tmp_path) == []
