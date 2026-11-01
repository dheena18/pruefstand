"""The shell steps of cassettes.yml, executed in scratch repositories (N2, N5)."""

import io
import os
import subprocess
import tarfile
from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "cassettes.yml"
PREFIX = "packages/pruefstand/tests/cassettes"


def _script(job: str, step: str) -> str:
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    for item in doc["jobs"][job]["steps"]:
        if item.get("name") == step:
            return str(item["run"])
    raise AssertionError(step)


def _run(script: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "GITHUB_RUN_ID": "1", "GITHUB_STEP_SUMMARY": str(cwd / "summary.md")}
    cmd = ["bash", "-e", "-o", "pipefail", "-c", script]
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, check=False)  # noqa: S603


def _git(repo: Path, *args: str) -> str:
    cmd = ["git", "-C", str(repo), *args]
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout  # noqa: S603


def _repo(path: Path) -> Path:
    path.mkdir()
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "t@example.org")
    _git(path, "config", "user.name", "t")
    for name in ("a.yaml", "b.yaml"):
        f = path / PREFIX / "llm" / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(f"{name} one\n", encoding="utf-8")
    (path / "keep.txt").write_text("k\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-qm", "init")
    return path


def _tar(path: Path, members: list[tuple[str, str, bytes | str]]) -> None:
    with tarfile.open(path, "w:gz") as tar:
        for name, kind, payload in members:
            info = tarfile.TarInfo(name)
            if kind == "file":
                data = payload if isinstance(payload, bytes) else payload.encode()
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
            elif kind == "symlink":
                info.type = tarfile.SYMTYPE
                info.linkname = str(payload)
                tar.addfile(info)
            else:
                info.type = tarfile.LNKTYPE
                info.linkname = str(payload)
                tar.addfile(info)


def _unpack(repo: Path) -> subprocess.CompletedProcess[str]:
    return _run(_script("push", "Unpack and validate"), repo)


def _stage(repo: Path) -> subprocess.CompletedProcess[str]:
    return _run(_script("push", "Stage and verify"), repo)


def test_pack_ships_added_and_modified_files_and_a_deletion_list(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "rec")
    (repo / PREFIX / "llm" / "a.yaml").write_text("two\n", encoding="utf-8")
    (repo / PREFIX / "llm" / "b.yaml").unlink()
    (repo / PREFIX / "llm" / "c.yaml").write_text("new\n", encoding="utf-8")
    done = _run(_script("record", "Pack changed cassettes"), repo)
    assert done.returncode == 0, done.stderr
    with tarfile.open(repo / "cassettes.tgz") as tar:
        names = sorted(tar.getnames())
        deleted = tar.extractfile("deleted.txt").read().decode().split()  # type: ignore[union-attr]
    assert names == sorted([f"{PREFIX}/llm/a.yaml", f"{PREFIX}/llm/c.yaml", "deleted.txt"])
    assert deleted == [f"{PREFIX}/llm/b.yaml"]


def test_pack_with_only_deletions_still_works(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "rec")
    (repo / PREFIX / "llm" / "b.yaml").unlink()
    done = _run(_script("record", "Pack changed cassettes"), repo)
    assert done.returncode == 0, done.stderr


def test_push_applies_changes_deletions_and_stages_only_cassettes(tmp_path: Path) -> None:
    rec = _repo(tmp_path / "rec")
    (rec / PREFIX / "llm" / "a.yaml").write_text("two\n", encoding="utf-8")
    (rec / PREFIX / "llm" / "b.yaml").unlink()
    (rec / PREFIX / "llm" / "c.yaml").write_text("new\n", encoding="utf-8")
    assert _run(_script("record", "Pack changed cassettes"), rec).returncode == 0
    push = _repo(tmp_path / "push")
    (push / "cassettes.tgz").write_bytes((rec / "cassettes.tgz").read_bytes())
    assert _unpack(push).returncode == 0
    done = _stage(push)
    assert done.returncode == 0, done.stderr
    staged = _git(push, "diff", "--cached", "--name-status").split("\n")
    assert sorted(x for x in staged if x) == sorted(
        [f"M\t{PREFIX}/llm/a.yaml", f"D\t{PREFIX}/llm/b.yaml", f"A\t{PREFIX}/llm/c.yaml"]
    )
    assert not (push / "deleted.txt").exists()


@pytest.mark.parametrize(
    "members",
    [
        [("deleted.txt", "file", ""), (f"{PREFIX}/llm/a.yaml", "symlink", "/etc/passwd")],
        [("deleted.txt", "file", ""), (f"{PREFIX}/llm/a.yaml", "hardlink", "keep.txt")],
        [("deleted.txt", "file", ""), ("keep.txt", "file", "overwritten")],
        [("deleted.txt", "file", ""), (f"{PREFIX}/../keep.txt", "file", "x")],
        [("deleted.txt", "file", "keep.txt\n")],
        [("deleted.txt", "file", f"{PREFIX}/../keep.txt\n")],
    ],
)
def test_unsafe_artefacts_are_rejected(
    tmp_path: Path, members: list[tuple[str, str, bytes | str]]
) -> None:
    push = _repo(tmp_path / "push")
    _tar(push / "cassettes.tgz", members)
    assert _unpack(push).returncode != 0
    assert (push / "keep.txt").read_text(encoding="utf-8") == "k\n"


def test_too_many_files_are_rejected(tmp_path: Path) -> None:
    push = _repo(tmp_path / "push")
    members: list[tuple[str, str, bytes | str]] = [("deleted.txt", "file", "")]
    members += [(f"{PREFIX}/llm/f{i}.yaml", "file", "x") for i in range(600)]
    _tar(push / "cassettes.tgz", members)
    assert _unpack(push).returncode != 0


def test_a_symlink_in_the_work_tree_fails_the_stage_step(tmp_path: Path) -> None:
    push = _repo(tmp_path / "push")
    link = push / PREFIX / "llm" / "evil.yaml"
    link.symlink_to("/etc/passwd")
    assert _stage(push).returncode != 0
