"""Check where tests live and that import roots do not clash (T0.1 S9, R9 X4.2, R12 N6.3).

Reads ``testpaths``, ``pythonpath`` and ``mypy_path`` from ``pyproject.toml`` and fails when
 * ``pythonpath`` and ``mypy_path`` differ;
 * a ``test_*.py`` file is outside the expanded ``testpaths``;
 * a root's ``tests/`` directory exists but is not covered by ``testpaths``;
 * a test directory contains an ``__init__.py``;
 * two import roots expose the same top-level non-test module or package name.
"""

import argparse
import tomllib
from collections import defaultdict
from collections.abc import Iterator, Sequence
from pathlib import Path

SKIP_DIRS = frozenset({"node_modules", "__pycache__", ".venv"})
TEST_ROOTS = ("packages/pruefstand/tests", "apps/rag-demo/tests")


def _visible(rel: Path) -> bool:
    return SKIP_DIRS.isdisjoint(rel.parts) and not any(p.startswith(".") for p in rel.parts)


def _rglob(root: Path, pattern: str) -> Iterator[Path]:
    for path in sorted(root.rglob(pattern)):
        if _visible(path.relative_to(root)):
            yield path


def _is_test_file(path: Path) -> bool:
    return path.name == "conftest.py" or (path.name.startswith("test_") and path.suffix == ".py")


def _load(root: Path) -> tuple[list[str], list[str], list[str]]:
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    pytest_cfg = data["tool"]["pytest"]["ini_options"]
    return pytest_cfg["testpaths"], pytest_cfg["pythonpath"], data["tool"]["mypy"]["mypy_path"]


def _expand(root: Path, testpaths: list[str]) -> list[Path]:
    return [p for pattern in testpaths for p in sorted(root.glob(pattern)) if p.is_dir()]


def _within(path: Path, dirs: list[Path]) -> bool:
    return any(path.is_relative_to(d) for d in dirs)


def check_roots_agree(pythonpath: list[str], mypy_path: list[str]) -> list[str]:
    """Fail when ``pythonpath`` and ``mypy_path`` are not the same ordered list (X4.2)."""
    if pythonpath == mypy_path:
        return []
    return [f"pythonpath != mypy_path: {sorted(set(pythonpath) ^ set(mypy_path))}"]


def check_locations(root: Path, testpaths: list[str], roots: list[str]) -> list[str]:
    """Check test files, uncovered ``<root>/tests`` dirs and ``__init__.py`` in test dirs."""
    dirs = _expand(root, testpaths)
    findings = []
    for path in _rglob(root, "test_*.py"):
        if not _within(path, dirs):
            findings.append(f"{path.relative_to(root).as_posix()}: test file outside testpaths")
    for rel in roots:
        tests_dir = root / rel / "tests"
        if tests_dir.is_dir() and not _within(tests_dir, dirs):
            findings.append(f"{rel}: {rel}/tests is not covered by testpaths")
    test_dirs = {d for base in dirs for d in [base, *(p for p in base.rglob("*") if p.is_dir())]}
    test_dirs |= {p for p in root.rglob("tests") if p.is_dir() and _visible(p.relative_to(root))}
    for directory in sorted(test_dirs):
        init = directory / "__init__.py"
        if init.exists():
            findings.append(f"{init.relative_to(root).as_posix()}: __init__.py in a test directory")
    return findings


def _only_tests(directory: Path) -> bool:
    files = list(_rglob(directory, "*.py"))
    return bool(files) and all(_is_test_file(f) for f in files)


def _exposed_name(entry: Path, *, is_tests_root: bool) -> str | None:
    if not _visible(Path(entry.name)):
        return None
    if entry.is_file():
        is_module = entry.suffix == ".py" and entry.name != "__init__.py"
        return entry.stem if is_module and not _is_test_file(entry) else None
    if entry.name == "tests" or not any(_rglob(entry, "*.py")):
        return None
    return None if is_tests_root and _only_tests(entry) else entry.name


def top_level_names(root: Path, rel: str) -> set[str]:
    """Return the top-level non-test module/package names a root exposes."""
    base = root / rel
    if not base.is_dir():
        return set()
    is_tests_root = rel in TEST_ROOTS
    names = (_exposed_name(e, is_tests_root=is_tests_root) for e in sorted(base.iterdir()))
    return {n for n in names if n}


def check_name_clashes(root: Path, roots: list[str]) -> list[str]:
    """Fail when two import roots expose the same top-level non-test name."""
    owners: dict[str, list[str]] = defaultdict(list)
    for rel in roots:
        for name in top_level_names(root, rel):
            owners[name].append(rel)
    return [
        f"module name {name!r} is exposed by several roots: {', '.join(rels)}"
        for name, rels in sorted(owners.items())
        if len(rels) > 1
    ]


def main(argv: Sequence[str] | None = None) -> int:
    """Run all checks; return 0 when clean, 1 when any finding was printed."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args(argv)
    testpaths, pythonpath, mypy_path = _load(args.root)
    findings = [
        *check_roots_agree(pythonpath, mypy_path),
        *check_locations(args.root, testpaths, mypy_path),
        *check_name_clashes(args.root, mypy_path),
    ]
    for finding in findings:
        print(finding)
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
