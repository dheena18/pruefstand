"""apply_models_artifact.sh: verify, restrict and copy the cassettes-models artefact."""

import hashlib
import stat
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "apply_models_artifact.sh"
GOOD = "packages/pruefstand/tests/cassettes/perturb/rewrite/a.json"
EVIL = ".github/workflows/evil.yml"


def _artefact(path: Path, files: dict[str, str], *, sums: bool = True) -> Path:
    lines = []
    for rel, text in files.items():
        target = path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        lines.append(f"{hashlib.sha256(text.encode()).hexdigest()}  ./{rel}")
    if sums:
        (path / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _apply(src: Path, root: Path) -> subprocess.CompletedProcess[str]:
    root.mkdir(exist_ok=True)
    cmd = ["bash", str(SCRIPT), str(src), str(root)]
    return subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603


def _refused(run: subprocess.CompletedProcess[str], root: Path, *rels: str) -> None:
    assert run.returncode != 0, run.stdout
    for rel in rels:
        assert not (root / rel).exists(), rel


def test_a_clean_artefact_is_copied_without_the_checksum_file(tmp_path: Path) -> None:
    src = _artefact(tmp_path / "src", {GOOD: '{"x": "Kündigung"}\n'})
    root = tmp_path / "repo"
    run = _apply(src, root)
    assert run.returncode == 0, run.stderr
    assert (root / GOOD).read_text(encoding="utf-8") == '{"x": "Kündigung"}\n'
    assert not (root / "SHA256SUMS.txt").exists()


def test_a_changed_file_is_refused_and_nothing_is_copied(tmp_path: Path) -> None:
    src = _artefact(tmp_path / "src", {GOOD: "one\n"})
    (src / GOOD).write_text("two\n", encoding="utf-8")
    _refused(_apply(src, tmp_path / "repo"), tmp_path / "repo", GOOD)


def test_a_listed_path_outside_the_result_locations_is_refused(tmp_path: Path) -> None:
    for rel in (EVIL, "scripts/evil.sh", "packages/pruefstand/src/x.py"):
        name = rel.replace("/", "_")
        run = _apply(_artefact(tmp_path / name, {rel: "x\n"}), tmp_path / ("repo_" + name))
        _refused(run, tmp_path / ("repo_" + name), rel)
        assert "unexpected path" in run.stderr


def test_an_unlisted_file_is_refused_even_on_a_good_path(tmp_path: Path) -> None:
    src = _artefact(tmp_path / "src", {GOOD: "one\n"})
    (src / EVIL).parent.mkdir(parents=True)
    (src / EVIL).write_text("on: push\n", encoding="utf-8")
    run = _apply(src, tmp_path / "repo")
    _refused(run, tmp_path / "repo", GOOD, EVIL)
    assert "unlisted" in run.stderr


def test_a_listed_file_that_is_missing_is_refused(tmp_path: Path) -> None:
    src = _artefact(tmp_path / "src", {GOOD: "one\n"})
    (src / GOOD).unlink()
    _refused(_apply(src, tmp_path / "repo"), tmp_path / "repo", GOOD)


def test_a_symlink_is_refused_listed_or_not(tmp_path: Path) -> None:
    secret = tmp_path / "outside.json"
    secret.write_text("secret\n", encoding="utf-8")
    link_rel = "packages/pruefstand/tests/cassettes/perturb/rewrite/link.json"
    src = _artefact(tmp_path / "listed", {GOOD: "one\n"})
    (src / link_rel).symlink_to(secret)
    digest = hashlib.sha256(b"secret\n").hexdigest()
    with (src / "SHA256SUMS.txt").open("a", encoding="utf-8") as sums:
        sums.write(f"{digest}  ./{link_rel}\n")
    run = _apply(src, tmp_path / "repo1")
    _refused(run, tmp_path / "repo1", GOOD, link_rel)
    assert "non-regular" in run.stderr
    other = _artefact(tmp_path / "unlisted", {GOOD: "one\n"})
    (other / "stray").symlink_to(secret)
    _refused(_apply(other, tmp_path / "repo2"), tmp_path / "repo2", GOOD)


def test_exec_bits_are_dropped(tmp_path: Path) -> None:
    src = _artefact(tmp_path / "src", {GOOD: "one\n"})
    (src / GOOD).chmod(0o755)
    root = tmp_path / "repo"
    assert _apply(src, root).returncode == 0
    assert stat.S_IMODE((root / GOOD).stat().st_mode) & 0o111 == 0


def test_traversal_is_refused(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    digest = hashlib.sha256(b"x\n").hexdigest()
    rel = "packages/pruefstand/tests/cassettes/perturb/../../../../../evil.json"
    (src / "SHA256SUMS.txt").write_text(f"{digest}  ./{rel}\n", encoding="utf-8")
    run = _apply(src, tmp_path / "repo")
    assert run.returncode != 0
    assert not (tmp_path / "evil.json").exists()


def test_a_file_over_the_size_cap_is_refused(tmp_path: Path) -> None:
    src = _artefact(tmp_path / "src", {GOOD: "x" * (8 * 1024 * 1024 + 1)})
    run = _apply(src, tmp_path / "repo")
    _refused(run, tmp_path / "repo", GOOD)
    assert "larger" in run.stderr


def test_a_missing_checksum_file_is_refused(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    assert _apply(tmp_path / "src", tmp_path / "repo").returncode != 0
