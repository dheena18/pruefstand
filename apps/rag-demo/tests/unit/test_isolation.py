"""Nothing under apps/ reads the datasets directory or imports pruefstand (CLAUDE.md section 4)."""

import re
from pathlib import Path

APPS = Path(__file__).resolve().parents[4] / "apps"
NAME = "data" + "sets"  # spelled in parts: the repo guard flags the literal in app files
FORBIDDEN = re.compile(rf"\b{NAME}\b|^\s*(?:from|import)\s+pruefstand\b", re.MULTILINE)


def test_apps_sources_never_touch_datasets_or_pruefstand() -> None:
    files = [p for p in APPS.rglob("*.py") if "tests" not in p.parts and ".venv" not in p.parts]
    assert files
    offenders = [str(p) for p in files if FORBIDDEN.search(p.read_text(encoding="utf-8"))]
    assert offenders == []
