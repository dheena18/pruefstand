"""Tests for scripts/deploy/assemble_pages_site.sh (T0.4 S6c, D243, N5.1, R13 P5.5)."""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
BASH = shutil.which("bash") or "bash"
DU = shutil.which("du") or "du"
SCRIPT = REPO / "scripts" / "deploy" / "assemble_pages_site.sh"
BUILD_ID = "0123456789abcdef0123456789abcdef01234567-42"
DOCS_HOME = "<html><title>Prüfstand docs home</title></html>"


def _run(
    tmp_path: Path, dashboard: str | Path, build_id: str | None = BUILD_ID, **env: str
) -> subprocess.CompletedProcess[str]:
    site = tmp_path / "site"
    if not site.exists():
        site.mkdir()
        (site / "index.html").write_text(DOCS_HOME, encoding="utf-8")
    full_env = {k: v for k, v in os.environ.items() if k not in {"BUILD_ID", "PAGES_MAX_BYTES"}}
    if build_id is not None:
        full_env["BUILD_ID"] = build_id
    full_env.update(env)
    return subprocess.run(  # noqa: S603  # fixed argv, no shell
        [BASH, str(SCRIPT), str(dashboard), str(site), str(tmp_path / "_pages")],
        capture_output=True,
        text=True,
        check=False,
        env=full_env,
    )


def test_placeholder_layout(tmp_path: Path) -> None:
    result = _run(tmp_path, "--placeholder")
    assert result.returncode == 0, result.stderr
    pages = tmp_path / "_pages"
    index = (pages / "index.html").read_text(encoding="utf-8")
    assert 'href="docs/"' in index
    assert (pages / "404.html").read_text(encoding="utf-8") == index
    assert (pages / "docs" / "index.html").read_text(encoding="utf-8") == DOCS_HOME
    assert (pages / ".nojekyll").is_file()
    assert re.search(r"\d+\s+" + re.escape(str(pages)), result.stdout)  # du -sb is printed


def test_build_id_file_is_the_build_id_and_a_newline(tmp_path: Path) -> None:
    assert _run(tmp_path, "--placeholder").returncode == 0
    assert (tmp_path / "_pages" / "build-id.txt").read_bytes() == f"{BUILD_ID}\n".encode()


@pytest.mark.parametrize(
    "bad", [None, "", "abc-1", "0123456789abcdef0123456789abcdef01234567", "G" * 40 + "-1"]
)
def test_missing_or_malformed_build_id_fails(tmp_path: Path, bad: str | None) -> None:
    result = _run(tmp_path, "--placeholder", build_id=bad)
    assert result.returncode == 1
    assert "BUILD_ID" in result.stderr
    assert not (tmp_path / "_pages").exists()


def test_dashboard_dir_is_copied_to_the_root(tmp_path: Path) -> None:
    dash = tmp_path / "dash"
    (dash / "_next").mkdir(parents=True)
    (dash / "index.html").write_text("<html>dashboard</html>", encoding="utf-8")
    (dash / "_next" / "a.js").write_text("1", encoding="utf-8")
    assert _run(tmp_path, dash).returncode == 0
    pages = tmp_path / "_pages"
    assert (pages / "index.html").read_text(encoding="utf-8") == "<html>dashboard</html>"
    assert (pages / "_next" / "a.js").is_file()
    assert (pages / "docs" / "index.html").is_file()
    assert (pages / ".nojekyll").is_file()


@pytest.mark.parametrize("clash", ["docs", "build-id.txt"])
def test_dashboard_dir_must_not_contain_docs_or_build_id(tmp_path: Path, clash: str) -> None:
    dash = tmp_path / "dash"
    dash.mkdir()
    (dash / "index.html").write_text("x", encoding="utf-8")
    if clash == "docs":
        (dash / "docs").mkdir()
    else:
        (dash / clash).write_text("x", encoding="utf-8")
    result = _run(tmp_path, dash)
    assert result.returncode == 1
    assert clash in result.stderr


def test_symlink_in_the_dashboard_artefact_is_refused(tmp_path: Path) -> None:
    dash = tmp_path / "dash"
    dash.mkdir()
    (dash / "index.html").write_text("x", encoding="utf-8")
    (dash / "leak").symlink_to("/etc/passwd")
    result = _run(tmp_path, dash)
    assert result.returncode == 1
    assert "symlink" in result.stderr
    assert "leak" in result.stderr


def test_missing_dashboard_dir_fails(tmp_path: Path) -> None:
    result = _run(tmp_path, tmp_path / "nope")
    assert result.returncode == 1
    assert "dashboard" in result.stderr


def test_size_cap_names_the_measured_size(tmp_path: Path) -> None:
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("x" * 5000, encoding="utf-8")
    result = _run(tmp_path, "--placeholder", PAGES_MAX_BYTES="1000")
    assert result.returncode == 1
    du = subprocess.check_output([DU, "-sb", str(tmp_path / "_pages")], text=True)  # noqa: S603
    measured = int(du.split()[0])
    assert str(measured) in result.stderr
    assert "1000" in result.stderr


def test_size_cap_default_is_800_mb(tmp_path: Path) -> None:
    assert "800000000" in SCRIPT.read_text(encoding="utf-8")


def test_existing_nonempty_output_dir_is_refused(tmp_path: Path) -> None:
    (tmp_path / "_pages").mkdir()
    (tmp_path / "_pages" / "stale").write_text("x", encoding="utf-8")
    assert _run(tmp_path, "--placeholder").returncode == 1


@pytest.mark.slow
def test_placeholder_with_a_real_mkdocs_build(tmp_path: Path) -> None:
    uv = shutil.which("uv")
    assert uv is not None
    built = tmp_path / "site"
    subprocess.run(  # noqa: S603  # fixed argv, no shell
        [uv, "run", "mkdocs", "build", "--strict", "--quiet", "-d", str(built)],
        cwd=REPO,
        check=True,
    )
    result = _run(tmp_path, "--placeholder")
    assert result.returncode == 0, result.stderr
    assert "Prüfstand" in (tmp_path / "_pages" / "docs" / "index.html").read_text(encoding="utf-8")
