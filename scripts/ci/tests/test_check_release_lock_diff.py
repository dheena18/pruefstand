"""T9.1a S1b: the release PR's uv.lock commit changes only the members' version lines (X2.9)."""

import subprocess
import sys
from pathlib import Path

from ci.check_release_lock_diff import main, problems
from ci.gate_router_regex import RELEASE_RULES, _line_exempt

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/ci/check_release_lock_diff.py"


def lock_diff(tmp_path: Path, edits: list[tuple[str, str]]) -> str:
    """A real ``git diff`` of the repository's uv.lock after ``edits`` (old, new) in a temp repo."""
    text = (ROOT / "uv.lock").read_text(encoding="utf-8")
    repo = tmp_path / "r"
    repo.mkdir(parents=True)
    (repo / "uv.lock").write_text(text, encoding="utf-8")
    git = ["git", "-C", str(repo), "-c", "user.email=t@example.invalid", "-c", "user.name=t"]
    for args in (["init", "-q"], ["add", "uv.lock"], ["commit", "-qm", "base"]):
        subprocess.run([*git, *args], check=True, capture_output=True, timeout=60)  # noqa: S603
    for old, new in edits:
        assert old in text, old
        text = text.replace(old, new, 1)
    (repo / "uv.lock").write_text(text, encoding="utf-8")
    done = subprocess.run(  # noqa: S603
        [*git, "diff", "--", "uv.lock"], check=True, capture_output=True, text=True, timeout=60
    )
    return done.stdout


MEMBER_BUMP = [
    ('name = "pruefstand"\nversion = "0.0.1"', 'name = "pruefstand"\nversion = "0.2.0"'),
    ('name = "rag-demo"\nversion = "0.0.1"', 'name = "rag-demo"\nversion = "0.2.0"'),
]
UV_LOCK_RULE = next(r for r in RELEASE_RULES if r["file"] == r"^uv\.lock$")


def test_a_member_version_bump_passes(tmp_path: Path) -> None:
    diff = lock_diff(tmp_path, MEMBER_BUMP)
    assert diff.count('+version = "0.2.0"') == 2
    assert problems(diff) == []
    assert _line_exempt(diff, UV_LOCK_RULE)  # the gate router agrees (one rule, two places)


def test_a_dependency_version_change_is_refused_by_name(tmp_path: Path) -> None:
    diff = lock_diff(
        tmp_path,
        [
            *MEMBER_BUMP,
            ('name = "anyio"\nversion = "4.15.1"', 'name = "anyio"\nversion = "4.16.0"'),
        ],
    )
    found = problems(diff)
    assert found
    assert all(line.startswith("anyio: ") for line in found)
    assert not _line_exempt(diff, UV_LOCK_RULE)


def test_a_hash_change_is_refused(tmp_path: Path) -> None:
    text = (ROOT / "uv.lock").read_text(encoding="utf-8")
    start = text.index('hash = "sha256:') + len('hash = "sha256:')
    old = text[start : start + 8]
    diff = lock_diff(tmp_path, [(f'hash = "sha256:{old}', 'hash = "sha256:00000000')])
    assert problems(diff)


def test_the_workspace_root_version_passes_but_nothing_else_of_it(tmp_path: Path) -> None:
    root = (
        'name = "pruefstand-workspace"\nversion = "0.0.1"',
        'name = "pruefstand-workspace"\nversion = "0.2.0"',
    )
    diff = lock_diff(tmp_path / "a", [*MEMBER_BUMP, root])
    assert problems(diff) == []  # D1292
    assert _line_exempt(diff, UV_LOCK_RULE)
    ws = 'name = "pruefstand-workspace"\nversion = "0.0.1"\n'
    other = (ws + 'source = { virtual = "." }', ws + 'source = { virtual = "./x" }')
    bad = lock_diff(tmp_path / "b", [other])
    assert [p.split(":")[0] for p in problems(bad)] == ["pruefstand-workspace"] * 2
    assert not _line_exempt(bad, UV_LOCK_RULE)


def test_an_empty_diff_passes_and_the_cli_exit_codes(tmp_path: Path) -> None:
    assert problems("") == []
    ok = tmp_path / "ok.diff"
    ok.write_text(lock_diff(tmp_path, MEMBER_BUMP), encoding="utf-8")
    assert main([str(ok)]) == 0
    bad = tmp_path / "bad.diff"
    bad.write_text(' name = "anyio"\n-version = "4"\n+version = "5"\n', encoding="utf-8")
    assert main([str(bad)]) == 1
    done = subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPT)],
        input="",
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert done.returncode == 0
