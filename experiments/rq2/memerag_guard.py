"""Guard: no MEMERAG-derived content outside ``data/derived/`` (T5.3 S5, CC BY-NC 4.0).

Every MEMERAG item carries ``"source": "memerag"``. This guard scans the publishable trees
(``datasets/``, ``apps/``, ``examples/`` and the HF export dir ``hf_export/``) for that marker.
``scripts/check_no_raw_data.py`` already fails on any tracked path with a ``memerag`` component;
this guard catches the content under any file name, tracked or not.
"""

import re
from collections.abc import Iterator
from pathlib import Path

GUARDED_DIRS: tuple[str, ...] = ("datasets", "apps", "examples", "hf_export")
SKIP_DIRS = frozenset({"node_modules", ".next", ".venv", "__pycache__", ".git", "out"})
TEXT_SUFFIXES = frozenset({".json", ".jsonl", ".yaml", ".yml", ".csv", ".tsv", ".txt", ".md"})
MARKER = re.compile(r'"source"\s*:\s*"memerag"')


def _walk(base: Path) -> Iterator[Path]:
    for path in sorted(base.iterdir()):
        if path.is_dir() and path.name not in SKIP_DIRS:
            yield from _walk(path)
        elif path.is_file() and path.suffix in TEXT_SUFFIXES:
            yield path


def find_memerag_content(root: Path) -> list[Path]:
    """Return every file under the guarded dirs of ``root`` that holds the MEMERAG marker.

    Args:
        root: Repository root.

    Returns:
        Offending paths relative to ``root`` (empty when clean).
    """
    hits: list[Path] = []
    for name in GUARDED_DIRS:
        base = root / name
        if not base.is_dir():
            continue
        for path in _walk(base):
            if MARKER.search(path.read_text(encoding="utf-8", errors="replace")):
                hits.append(path.relative_to(root))
    return hits
