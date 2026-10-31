import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MAKEFILE = REPO / "Makefile"


def _dry_run_typecheck(cwd: Path) -> list[str]:
    result = subprocess.run(  # noqa: S603
        [shutil.which("make") or "make", "-n", "-f", str(MAKEFILE), "typecheck"],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if "mypy" in line]


def test_typecheck_runs_one_mypy_per_existing_root(tmp_path: Path) -> None:
    (tmp_path / "packages/pruefstand/src").mkdir(parents=True)
    (tmp_path / "scripts").mkdir()
    text = "\n".join(_dry_run_typecheck(tmp_path))
    assert text.count("uv run mypy") == 2
    assert "packages/pruefstand/src" in text
    assert "scripts" in text
    assert "apps/rag-demo" not in text


def test_typecheck_never_passes_two_roots_to_one_mypy(tmp_path: Path) -> None:
    for root in ("packages/pruefstand/src", "scripts", "tools"):
        (tmp_path / root).mkdir(parents=True)
    text = "\n".join(_dry_run_typecheck(tmp_path))
    for segment in text.split("uv run mypy")[1:]:
        first = segment.split(";")[0].split("||")[0].split()
        assert len(first) == 1, segment


def test_typecheck_in_the_real_repo_covers_every_existing_root() -> None:
    text = "\n".join(_dry_run_typecheck(REPO))
    for root in ("packages/pruefstand/src", "apps/rag-demo/src", "scripts"):
        assert root in text
