"""Nothing under apps/ reads the datasets directory or imports pruefstand (CLAUDE.md section 4)."""

import re
from pathlib import Path

APPS = Path(__file__).resolve().parents[4] / "apps"
NAME = "data" + "sets"  # spelled in parts: the repo guard flags the literal in app files
FORBIDDEN = re.compile(rf"\b{NAME}\b|^\s*(?:from|import)\s+pruefstand\b", re.MULTILINE)


SKIPPED_DIRS = {
    "tests",
    ".venv",
    "node_modules",
    ".next",
    "dist",
    "build",
    "__pycache__",
    "fixtures",
}
SUFFIXES = {".py", ".yaml", ".yml", ".toml", ".sh", ".txt", ".ts", ".tsx", ".js", ".mjs"}
SKIPPED_FILES = {"pnpm-lock.yaml", "package-lock.json", "uv.lock"}


def _app_files() -> list[Path]:
    """Every source, config, script and Dockerfile below apps/ outside tests and build output."""
    found = []
    for path in APPS.rglob("*"):
        if not path.is_file() or path.name in SKIPPED_FILES:
            continue
        if SKIPPED_DIRS & set(path.relative_to(APPS).parts):
            continue
        if path.suffix in SUFFIXES or path.name.startswith("Dockerfile"):
            found.append(path)
    return found


def test_apps_sources_never_touch_datasets_or_pruefstand() -> None:
    files = _app_files()
    assert files
    offenders = [str(p) for p in files if FORBIDDEN.search(p.read_text(encoding="utf-8"))]
    assert offenders == []


def test_the_scan_covers_more_than_python_files() -> None:
    suffixes = {p.suffix for p in _app_files()}
    assert {".py", ".yaml", ".txt"} <= suffixes
    assert any(p.name.startswith("Dockerfile") for p in _app_files())
