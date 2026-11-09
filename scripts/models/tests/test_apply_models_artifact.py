"""apply_models_artifact.sh: verify, restrict and copy the cassettes-models artefact."""

import hashlib
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "apply_models_artifact.sh"
GOOD = "packages/pruefstand/tests/cassettes/perturb/rewrite/a.json"


def _artefact(path: Path, files: dict[str, str]) -> Path:
    lines = []
    for rel, text in files.items():
        target = path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        lines.append(f"{hashlib.sha256(text.encode()).hexdigest()}  ./{rel}")
    (path / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _apply(src: Path, root: Path) -> subprocess.CompletedProcess[str]:
    cmd = ["bash", str(SCRIPT), str(src), str(root)]
    return subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603


def test_a_clean_artefact_is_copied_without_the_checksum_file(tmp_path: Path) -> None:
    src = _artefact(tmp_path / "src", {GOOD: '{"x": "Kündigung"}\n'})
    root = tmp_path / "repo"
    root.mkdir()
    run = _apply(src, root)
    assert run.returncode == 0, run.stderr
    assert (root / GOOD).read_text(encoding="utf-8") == '{"x": "Kündigung"}\n'
    assert not (root / "SHA256SUMS.txt").exists()


def test_a_changed_file_is_refused_and_nothing_is_copied(tmp_path: Path) -> None:
    src = _artefact(tmp_path / "src", {GOOD: "one\n"})
    (src / GOOD).write_text("two\n", encoding="utf-8")
    root = tmp_path / "repo"
    root.mkdir()
    assert _apply(src, root).returncode != 0
    assert not (root / GOOD).exists()


def test_a_path_outside_the_result_locations_is_refused(tmp_path: Path) -> None:
    for rel in (".github/workflows/ci.yml", "scripts/evil.sh", "packages/pruefstand/src/x.py"):
        src = _artefact(tmp_path / rel.replace("/", "_"), {rel: "x\n"})
        root = tmp_path / ("repo_" + rel.replace("/", "_"))
        root.mkdir()
        run = _apply(src, root)
        assert run.returncode != 0
        assert "unexpected path" in run.stderr
        assert not (root / rel).exists()


def test_a_missing_checksum_file_is_refused(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    assert _apply(tmp_path / "src", tmp_path).returncode != 0
