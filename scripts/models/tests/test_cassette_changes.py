"""scripts/models/cassettes_changed.sh: change detection of the weekly cassettes workflow (M2)."""

import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "cassettes_changed.sh"
CASSETTES = "packages/pruefstand/tests/cassettes"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)  # noqa: S603, S607


def _repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.org")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / CASSETTES / "llm").mkdir(parents=True)
    (tmp_path / CASSETTES / "llm" / "a.yaml").write_text("one\n", encoding="utf-8")
    (tmp_path / "other.txt").write_text("x\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "init")
    return tmp_path


def _changed(repo: Path) -> str:
    out = subprocess.run(  # noqa: S603
        ["bash", str(SCRIPT)], cwd=repo, capture_output=True, text=True, check=True
    )
    return out.stdout.strip()


def test_clean_tree_is_unchanged(tmp_path: Path) -> None:
    assert _changed(_repo(tmp_path)) == "changed=false"


def test_modified_cassette_is_detected(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / CASSETTES / "llm" / "a.yaml").write_text("two\n", encoding="utf-8")
    assert _changed(repo) == "changed=true"


def test_new_cassette_is_detected(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / CASSETTES / "llm" / "backend").mkdir()
    (repo / CASSETTES / "llm" / "backend" / "new.json").write_text("{}\n", encoding="utf-8")
    assert _changed(repo) == "changed=true"


def test_changes_outside_the_cassettes_are_ignored(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "other.txt").write_text("y\n", encoding="utf-8")
    assert _changed(repo) == "changed=false"
