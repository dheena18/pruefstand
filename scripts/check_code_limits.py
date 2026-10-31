"""Fail on files over 300 lines, functions over 50 body lines and ``datasets/`` strings in apps.

CLAUDE.md §5 and coding-standards §1.3 (T0.1 S8, run by ``make file-size``). Prints
``path:line name length`` for every long function and ``path: N lines`` for every long file.
"""

import argparse
import ast
from collections.abc import Iterator, Sequence
from pathlib import Path

MAX_FILE_LINES = 300
MAX_FUNCTION_LINES = 50
SCAN_DIRS = (
    "packages", "apps", "scripts", "tools", "experiments", "benchmarks", "data", "action", "infra",
)  # fmt: skip
SKIP_DIRS = frozenset({"node_modules", "__pycache__", ".venv"})
FORBIDDEN_IN_APPS = "datasets/"


def iter_python_files(root: Path) -> Iterator[Path]:
    """Yield every ``.py`` file below the scanned top-level directories of ``root``."""
    for name in SCAN_DIRS:
        base = root / name
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            parts = path.relative_to(root).parts
            if SKIP_DIRS.isdisjoint(parts) and not any(p.startswith(".") for p in parts):
                yield path


def check_functions(tree: ast.AST, rel: str) -> list[str]:
    """Return one finding per function whose body is longer than the limit."""
    findings = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            first = node.body[0].lineno
            length = (node.end_lineno or first) - first + 1
            if length > MAX_FUNCTION_LINES:
                findings.append(f"{rel}:{node.lineno} {node.name} {length}")
    return findings


def check_file(path: Path, root: Path) -> list[str]:
    """Return all findings of one file (length, function length, datasets/ in apps)."""
    rel = path.relative_to(root).as_posix()
    text = path.read_text(encoding="utf-8")
    findings = []
    line_count = len(text.splitlines())
    if line_count > MAX_FILE_LINES:
        findings.append(f"{rel}: {line_count} lines (max {MAX_FILE_LINES})")
    findings += check_functions(ast.parse(text, filename=rel), rel)
    if rel.startswith("apps/") and FORBIDDEN_IN_APPS in text:
        findings.append(f"{rel}: contains {FORBIDDEN_IN_APPS!r} (apps must not read the datasets)")
    return findings


def main(argv: Sequence[str] | None = None) -> int:
    """Run the checks; return 0 when clean, 1 when any finding was printed."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args(argv)
    findings = [f for path in iter_python_files(args.root) for f in check_file(path, args.root)]
    for finding in findings:
        print(finding)
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
